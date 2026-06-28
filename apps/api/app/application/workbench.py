import hashlib
import hmac
import math
import re
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeoutError
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, TypeVar
from urllib.parse import urlparse
from uuid import uuid4

import httpx

from app.application.ai import (
    AiMockValidationService,
    AiProxyConfig,
    AiRelayService,
    AiServiceUnavailable,
    OpenAiCompatibleAiService,
    RightCodeAiService,
    attach_ai_decision_signal,
)
from app.application.ai_providers import AI_PROVIDER_TEMPLATES, ai_provider_requires_api_key
from app.application.news import CryptoNewsService
from app.application.notifications import FeishuNotificationService
from app.application.ports import (
    AiAnalysisRepository,
    AuditLogRepository,
    PortfolioRepository,
    RiskRepository,
    StrategyRepository,
    SystemStateRepository,
)
from app.application.risk import RiskEngine, RiskThresholds
from app.application.strategies import (
    BacktestEngine,
    SignalEngine,
    StrategyRegistry,
    default_strategy_registry,
)
from app.application.trading import DryRunTradingService
from app.core.config import Settings
from app.domain.models import (
    AiAnalysis,
    AiProxyConnectionTestRequest,
    AiProxyConnectionTestResult,
    AiProxySettingsUpdateRequest,
    AiProxyStatus,
    AuditLog,
    AllowedDirection,
    BacktestRequest,
    BacktestResult,
    Balance,
    Candle,
    ConnectionState,
    DailyPushResult,
    DailyPushSettingsUpdateRequest,
    DashboardResponse,
    DryRunOrderRequest,
    ExchangeAccountConnectionTestRequest,
    ExchangeAccountConnectionTestResult,
    ExchangeId,
    ExchangeAccountSettingsUpdate,
    ExchangeAccountSettingsUpdateRequest,
    ExchangeStatus,
    HistoricalDataSyncRequest,
    HistoricalDataSyncResult,
    LiveCancelOrderRequest,
    LiveOrderRequest,
    ManualClosePositionRequest,
    MarketOverview,
    Metric,
    NewsFeedSource,
    NewsSentimentSummary,
    NotificationChannelSettingsUpdate,
    NotificationProvider,
    NotificationResult,
    NotificationSettingsUpdateRequest,
    NotificationTestRequest,
    Order,
    Position,
    RiskEvent,
    RiskLevel,
    RiskStatus,
    RiskStatusResponse,
    SettingsSummary,
    Severity,
    SpotSignalAction,
    StrategyConfig,
    StrategySignal,
    StrategyUpdateRequest,
    SystemControlState,
    SystemControlUpdateRequest,
    SystemStatus,
    TradeDecisionTrace,
    TradingMode,
    TradingSummary,
    utc_now,
)
from app.infrastructure.exchanges import (
    ExchangeMarketDataError,
    ExchangeTradingError,
    ExchangeTradingNotConfiguredError,
    get_spot_market_client,
    get_spot_trading_client,
)
from app.infrastructure.exchanges.base import SpotOrderRequest
from app.infrastructure.exchanges.binance import BinanceSpotMarketClient
from app.infrastructure.exchanges.ccxt_spot import CcxtSpotTradingClient
from app.infrastructure.exchanges.okx import OkxSpotMarketClient

OKX_HISTORY_CANDLE_LIMIT = 300
MARKET_ANALYSIS_SYMBOLS_BY_EXCHANGE: dict[ExchangeId, tuple[str, ...]] = {
    ExchangeId.BINANCE: ("BTC/USDT", "ETH/USDT", "SOL/USDT", "DOGE/USDT", "BNB/USDT"),
    ExchangeId.OKX: ("BTC/USDT", "ETH/USDT", "SOL/USDT", "DOGE/USDT", "OKB/USDT"),
}


@dataclass(frozen=True)
class TimedCacheEntry:
    value: Any
    expires_at: float


@dataclass(frozen=True)
class SystemMarketStatusSnapshot:
    exchanges: tuple[ExchangeStatus, ...]
    data_checked_at: datetime | None


@dataclass(frozen=True)
class CandleCacheWriteResult:
    inserted: int = 0
    updated: int = 0


@dataclass(frozen=True)
class PortfolioContext:
    balances: list[Balance]
    positions: list[Position]
    open_orders: list[Order]
    source: str


def _to_db_timestamp(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value
    return value.astimezone(timezone.utc).replace(tzinfo=None)


def _from_db_timestamp(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


_MARKET_OVERVIEW_CACHE: dict[tuple[str, str, str, int, str], TimedCacheEntry] = {}
_SYSTEM_MARKET_STATUS_CACHE: dict[tuple[str, str, str, str], TimedCacheEntry] = {}
_EXTERNAL_FAILURE_COOLDOWNS: dict[tuple[str, ...], float] = {}
_AI_ANALYSIS_CACHE: dict[tuple[str, str, str], TimedCacheEntry] = {}
_NEWS_SENTIMENT_CACHE: dict[tuple[str, int], TimedCacheEntry] = {}
_PORTFOLIO_SNAPSHOT_CACHE: dict[tuple[str, ...], TimedCacheEntry] = {}
_LIVE_PORTFOLIO_EXECUTOR = ThreadPoolExecutor(max_workers=8, thread_name_prefix="live-portfolio")
T = TypeVar("T")

STABLE_QUOTE_ASSETS: frozenset[str] = frozenset(
    {"USDT", "USDC", "BUSD", "FDUSD", "TUSD", "DAI", "USD"},
)


class WorkbenchApplicationService:
    """Application facade for the local quant validation workbench.

    This service composes real providers/repositories. It deliberately does not synthesize
    account assets, positions, orders, logs, or backtest trades.
    """

    def __init__(
        self,
        settings: Settings,
        portfolio_repository: PortfolioRepository,
        strategy_repository: StrategyRepository,
        audit_log_repository: AuditLogRepository,
        risk_repository: RiskRepository,
        ai_analysis_repository: AiAnalysisRepository,
        system_state_repository: SystemStateRepository,
    ) -> None:
        self.settings = settings
        self.portfolio_repository = portfolio_repository
        self.strategy_repository = strategy_repository
        self.audit_log_repository = audit_log_repository
        self.risk_repository = risk_repository
        self.ai_analysis_repository = ai_analysis_repository
        self.system_state_repository = system_state_repository
        self.ai_service = AiRelayService.from_settings(settings) or AiMockValidationService()
        self.strategy_registry: StrategyRegistry = default_strategy_registry()
        self.signal_engine = SignalEngine(self.strategy_registry)
        self.backtest_engine = BacktestEngine(self.strategy_registry)
        self.risk_engine = RiskEngine()
        self.trading_service = DryRunTradingService()
        self.notification_service = FeishuNotificationService(settings)
        self.news_service = CryptoNewsService(settings)

    def _reload_settings(self, env_file: Path | None = None) -> None:
        self.settings = Settings(_env_file=env_file) if env_file is not None else Settings()
        self.ai_service = AiRelayService.from_settings(self.settings) or AiMockValidationService()
        self.notification_service = FeishuNotificationService(self.settings)
        self.news_service = CryptoNewsService(self.settings)

    def get_system_status(self, probe: bool = True) -> SystemStatus:
        requested_mode = TradingMode(self.settings.trading_mode)
        mode = requested_mode if self.settings.live_trading_enabled else TradingMode.DRY_RUN
        exchanges, data_latency_seconds = self._current_public_market_status(probe=probe)

        ai_proxy = self._current_ai_proxy_status()
        state = self.system_state_repository.get_state()
        return SystemStatus(
            trading_mode=mode,
            live_enabled=self.settings.live_trading_enabled,
            paused=state.paused,
            kill_switch_armed=state.kill_switch_armed,
            data_latency_seconds=data_latency_seconds,
            exchanges=exchanges,
            ai_proxy=ai_proxy,
        )

    def update_system_control(self, request: SystemControlUpdateRequest) -> SystemControlState:
        current = self.system_state_repository.get_state()
        updated = SystemControlState(
            paused=request.paused if request.paused is not None else current.paused,
            kill_switch_armed=(
                request.kill_switch_armed
                if request.kill_switch_armed is not None
                else current.kill_switch_armed
            ),
            reason=request.reason,
        )
        saved = self.system_state_repository.save_state(updated)
        self.audit_log_repository.append_log(
            AuditLog(
                level=Severity.CRITICAL if saved.kill_switch_armed else Severity.WARNING,
                module="system",
                message=(
                    "System control updated: "
                    f"paused={str(saved.paused).lower()}, "
                    f"kill_switch_armed={str(saved.kill_switch_armed).lower()}, "
                    f"reason={saved.reason}"
                ),
                correlation_id=self._correlation_id("system"),
            ),
        )
        return saved

    def get_dashboard(self, refresh: bool = False) -> DashboardResponse:
        portfolio = self._current_portfolio_context(include_open_orders=False)
        latest_logs = self.audit_log_repository.list_logs(limit=5)
        ai = self._get_dashboard_ai_snapshot(refresh=refresh)
        risk = self.get_risk_status(
            ai=ai,
            balances=portfolio.balances,
            positions=portfolio.positions,
        )
        equity = self._portfolio_equity(portfolio.balances, portfolio.positions)

        return DashboardResponse(
            system=self.get_system_status(probe=refresh),
            metrics=[
                Metric(
                    label="资产净值",
                    value=f"${equity:,.2f}",
                    detail=(
                        "from live account snapshot"
                        if portfolio.source == "live"
                        else "from portfolio repository"
                    ),
                    severity=Severity.WARNING if equity == 0 else Severity.SUCCESS,
                ),
                Metric(label="今日盈亏", value="$0", detail="no realized PnL source", severity=Severity.INFO),
                Metric(label="最大回撤", value="0%", detail="no equity history", severity=Severity.INFO),
                Metric(
                    label="当前仓位",
                    value=str(len(portfolio.positions)),
                    detail="spot positions",
                    severity=Severity.SUCCESS,
                ),
                Metric(
                    label="风控状态",
                    value=risk.status.value,
                    detail=risk.summary,
                    severity=Severity.WARNING,
                ),
                Metric(
                    label="AI 风险",
                    value=ai.risk_level.value,
                    detail=f"{ai.provider}/{ai.model}",
                    severity=Severity.WARNING,
                ),
            ],
            equity_curve=[],
            positions=portfolio.positions,
            latest_signals=self.strategy_repository.list_signals(limit=5),
            ai=ai,
            latest_logs=latest_logs,
        )

    def _get_dashboard_ai_snapshot(self, refresh: bool = False) -> AiAnalysis:
        if not refresh:
            cached = self._cached_ai_analysis_snapshot()
            if cached is not None:
                return cached

            latest = self.ai_analysis_repository.get_latest_analysis()
            if latest is not None:
                return latest

            return self._dashboard_ai_snapshot_unavailable()

        try:
            return self.get_ai_analysis(refresh=True)
        except TypeError:
            # Some tests replace get_ai_analysis with a no-argument stub.
            return self.get_ai_analysis()  # type: ignore[call-arg]

    def _dashboard_ai_snapshot_unavailable(
        self,
        scope: str = "symbol",
        symbol: str | None = None,
        exchange: ExchangeId | None = None,
    ) -> AiAnalysis:
        resolved_scope = "market" if scope == "market" else "symbol"
        resolved_symbol = "MARKET" if resolved_scope == "market" else symbol or self.settings.default_symbol
        analysis = AiAnalysis(
            analysis_scope=resolved_scope,
            symbol=resolved_symbol,
            market_regime="ai_snapshot_unavailable",
            sentiment_score=0,
            risk_level=RiskLevel.HIGH,
            event_risk=True,
            allowed_direction=AllowedDirection.NONE,
            confidence=0,
            provider="local_dashboard_fallback",
            model="snapshot-unavailable",
            rationale=[
                "No cached AI analysis snapshot is available; a conservative local fallback was used.",
            ],
            structured_payload={
                "analysis_scope": resolved_scope,
                "symbol": resolved_symbol,
                "fallback_reason": "ai_snapshot_unavailable",
            },
        )
        return attach_ai_decision_signal(
            analysis,
            scope=resolved_scope,
            symbol=resolved_symbol,
            exchange=exchange,
        )

    def get_market_overview(
        self,
        symbol: str | None = None,
        timeframe: str | None = None,
        exchange: ExchangeId | None = None,
        limit: int = 500,
        before: datetime | None = None,
        prefer_live: bool = True,
        refresh: bool = False,
        allow_stale_local: bool = False,
    ) -> MarketOverview:
        resolved_symbol = symbol or self.settings.default_symbol
        resolved_timeframe = timeframe or self.settings.default_timeframe
        resolved_exchange = exchange or ExchangeId(self.settings.default_exchange)
        resolved_limit = max(50, min(limit, 1000))

        cache_key = (
            resolved_exchange.value,
            resolved_symbol,
            resolved_timeframe,
            resolved_limit,
            before.isoformat() if before is not None else "",
        )

        if before is not None:
            local_market = self._get_local_market_overview(
                resolved_symbol,
                resolved_timeframe,
                resolved_exchange,
                resolved_limit,
                before=before,
                allow_stale=True,
            )
            if local_market is not None:
                return local_market

            historical_market = self._get_historical_market_overview(
                symbol=resolved_symbol,
                timeframe=resolved_timeframe,
                exchange=resolved_exchange,
                limit=resolved_limit,
                before=before,
            )
            if historical_market is not None:
                return historical_market

            return self._empty_market_overview(
                symbol=resolved_symbol,
                timeframe=resolved_timeframe,
                exchange=resolved_exchange,
                data_integrity="local_cache_empty",
            )

        if not refresh:
            cached_market = self._get_market_cache(cache_key)
            if cached_market is not None:
                return cached_market

        if prefer_live and self.settings.enable_public_exchange_data:
            cached_market = self._get_market_cache(cache_key)
            if not refresh and cached_market is not None:
                return cached_market

            failure_key = ("market", *cache_key[:3])
            if self._is_failure_cooling_down(failure_key):
                local_market = self._get_local_market_overview(
                    resolved_symbol,
                    resolved_timeframe,
                    resolved_exchange,
                    resolved_limit,
                    allow_stale=allow_stale_local,
                )
                if local_market is not None:
                    return local_market
                return self._empty_market_overview(
                    symbol=resolved_symbol,
                    timeframe=resolved_timeframe,
                    exchange=resolved_exchange,
                    data_integrity="exchange_error_cooling_down",
                )

            try:
                market = self._get_public_exchange_market_overview(
                    resolved_symbol,
                    resolved_timeframe,
                    resolved_exchange,
                    resolved_limit,
                )
                self._set_market_cache(cache_key, market)
                return market
            except ExchangeMarketDataError as exc:
                self._set_failure_cooldown(failure_key)
                local_market = self._get_local_market_overview(
                    resolved_symbol,
                    resolved_timeframe,
                    resolved_exchange,
                    resolved_limit,
                    allow_stale=allow_stale_local,
                )
                if local_market is not None:
                    return local_market
                return self._empty_market_overview(
                    symbol=resolved_symbol,
                    timeframe=resolved_timeframe,
                    exchange=resolved_exchange,
                    data_integrity=f"exchange_error: {exc}",
                )

        local_market = self._get_local_market_overview(
            resolved_symbol,
            resolved_timeframe,
            resolved_exchange,
            resolved_limit,
            allow_stale=allow_stale_local,
        )
        if local_market is not None:
            return local_market

        if not prefer_live:
            return self._empty_market_overview(
                symbol=resolved_symbol,
                timeframe=resolved_timeframe,
                exchange=resolved_exchange,
                data_integrity="local_cache_empty",
            )

        return self._empty_market_overview(
            symbol=resolved_symbol,
            timeframe=resolved_timeframe,
            exchange=resolved_exchange,
        )

    def get_strategies(self) -> list[StrategyConfig]:
        configured = {strategy.id: strategy for strategy in self._default_strategies()}
        configured.update({strategy.id: strategy for strategy in self.strategy_repository.list_strategies()})
        recent_signals = self.strategy_repository.list_signals(limit=100)
        return [
            self._merge_strategy_definition(strategy).model_copy(
                update={
                    "recent_signals": [
                        signal for signal in recent_signals if signal.strategy == strategy.id
                    ][:10],
                },
            )
            for strategy in configured.values()
        ]

    def update_strategy(
        self,
        strategy_id: str,
        request: StrategyUpdateRequest,
    ) -> StrategyConfig:
        strategy = self.strategy_repository.get_strategy(strategy_id) or self._default_strategy(strategy_id)
        if strategy is None:
            raise ValueError(f"Unknown strategy: {strategy_id}")
        strategy = self._merge_strategy_definition(strategy)

        updated = strategy.model_copy(
            update={
                "enabled": request.enabled if request.enabled is not None else strategy.enabled,
                "mode": request.mode if request.mode is not None else strategy.mode,
                "parameters": request.parameters
                if request.parameters is not None
                else strategy.parameters,
                "risk_controls": request.risk_controls
                if request.risk_controls is not None
                else strategy.risk_controls,
                "status": "ready" if request.enabled is not False else "disabled",
            },
            deep=True,
        )
        saved = self.strategy_repository.save_strategy(updated)
        self.audit_log_repository.append_log(
            AuditLog(
                level=Severity.INFO,
                module="strategy",
                strategy=strategy_id,
                message=f"Strategy configuration updated: {strategy_id}",
                correlation_id=self._correlation_id("strategy"),
            ),
        )
        return self._merge_strategy_definition(saved)

    def generate_strategy_signals(
        self,
        symbol: str | None = None,
        timeframe: str | None = None,
        exchange: ExchangeId | None = None,
        limit: int = 200,
    ) -> list[StrategySignal]:
        resolved_symbol = symbol or self.settings.default_symbol
        resolved_timeframe = timeframe or self.settings.default_timeframe
        resolved_exchange = exchange or ExchangeId(self.settings.default_exchange)
        market = self.get_market_overview(
            symbol=resolved_symbol,
            timeframe=resolved_timeframe,
            exchange=resolved_exchange,
            limit=limit,
            prefer_live=True,
        )
        signals: list[StrategySignal] = []
        for strategy in self.get_strategies():
            if not strategy.enabled or strategy.mode == "risk_filter":
                continue
            correlation_id = self._correlation_id("signal")
            signal = self.signal_engine.generate(
                strategy=strategy,
                candles=market.candles,
                symbol=resolved_symbol,
                correlation_id=correlation_id,
            )
            if signal is None:
                continue
            saved = self.strategy_repository.append_signal(signal)
            self.audit_log_repository.append_log(
                AuditLog(
                    level=Severity.INFO,
                    module="strategy",
                    symbol=resolved_symbol,
                    strategy=strategy.id,
                    message=f"Strategy signal generated: action={saved.action.value}, reason={saved.reason}",
                    correlation_id=correlation_id,
                ),
            )
            signals.append(saved)
        return signals

    def run_backtest(self, request: BacktestRequest) -> BacktestResult:
        definition = self.strategy_registry.get_definition(request.strategy_id)
        if definition is None or not definition.supports_backtest:
            return self._empty_backtest_result(
                request=request,
                status="unsupported_strategy",
                message=f"Unsupported backtesting strategy: {request.strategy_id}",
            )

        strategy = self.strategy_repository.get_strategy(request.strategy_id) or self._default_strategy(
            request.strategy_id,
        )
        if strategy is None:
            return self._empty_backtest_result(
                request=request,
                status="strategy_not_found",
                message=f"Strategy not found: {request.strategy_id}",
            )
        if not strategy.enabled:
            return self._empty_backtest_result(
                request=request,
                status="strategy_disabled",
                message=f"Strategy disabled: {request.strategy_id}",
            )

        candles = self._get_local_market_candles(
            symbol=request.symbol,
            timeframe=request.timeframe,
            exchange=request.exchange,
            start_at=self._parse_date_boundary(request.start_date),
            end_at=self._parse_date_boundary(request.end_date, end_of_day=True),
        )
        if not candles:
            return self._empty_backtest_result(
                request=request,
                status="data_unavailable",
                message=(
                    "Local historical market data unavailable. "
                    "Run historical data sync for this symbol/timeframe/date range first."
                ),
            )

        result = self.backtest_engine.run(request=request, strategy=strategy, candles=candles)
        self.audit_log_repository.append_log(
            AuditLog(
                level=Severity.INFO,
                module="backtest",
                symbol=request.symbol,
                strategy=request.strategy_id,
                message=f"Backtest finished with status={result.status}, trades={result.trade_count}",
                correlation_id=self._correlation_id("backtest"),
            ),
        )
        return result

    def sync_historical_market_data(
        self,
        request: HistoricalDataSyncRequest,
    ) -> HistoricalDataSyncResult:
        if self.settings.repository_backend != "mysql":
            return HistoricalDataSyncResult(
                symbol=request.symbol,
                exchange=request.exchange,
                timeframe=request.timeframe,
                start_date=request.start_date,
                end_date=request.end_date,
                fetched=0,
                inserted=0,
                updated=0,
                status="repository_unavailable",
                message="Historical sync requires REPOSITORY_BACKEND=mysql",
            )

        try:
            start_at = self._parse_date_boundary(request.start_date)
            end_at = self._parse_date_boundary(request.end_date, end_of_day=True)
        except ValueError as exc:
            return HistoricalDataSyncResult(
                symbol=request.symbol,
                exchange=request.exchange,
                timeframe=request.timeframe,
                start_date=request.start_date,
                end_date=request.end_date,
                fetched=0,
                inserted=0,
                updated=0,
                status="invalid_range",
                message=f"Invalid date range: {exc}",
            )
        if end_at <= start_at:
            return HistoricalDataSyncResult(
                symbol=request.symbol,
                exchange=request.exchange,
                timeframe=request.timeframe,
                start_date=request.start_date,
                end_date=request.end_date,
                fetched=0,
                inserted=0,
                updated=0,
                status="invalid_range",
                message="end_date must be after start_date",
            )

        cached_candles = self._get_local_market_candles(
            symbol=request.symbol,
            timeframe=request.timeframe,
            exchange=request.exchange,
            start_at=start_at,
            end_at=end_at,
        )
        expected_candles = self._expected_candle_count(
            timeframe=request.timeframe,
            start_at=start_at,
            end_at=end_at,
        )
        if len(cached_candles) >= expected_candles:
            return HistoricalDataSyncResult(
                symbol=request.symbol,
                exchange=request.exchange,
                timeframe=request.timeframe,
                start_date=request.start_date,
                end_date=request.end_date,
                fetched=len(cached_candles),
                inserted=0,
                updated=0,
                first_timestamp=cached_candles[0].timestamp if cached_candles else None,
                last_timestamp=cached_candles[-1].timestamp if cached_candles else None,
                status="completed",
                message="Historical candles already available in local market_candles",
            )

        try:
            candles = self._fetch_historical_candles(
                exchange=request.exchange,
                symbol=request.symbol,
                timeframe=request.timeframe,
                start_at=start_at,
                end_at=end_at,
            )
        except ExchangeMarketDataError as exc:
            return HistoricalDataSyncResult(
                symbol=request.symbol,
                exchange=request.exchange,
                timeframe=request.timeframe,
                start_date=request.start_date,
                end_date=request.end_date,
                fetched=0,
                inserted=0,
                updated=0,
                status="exchange_error",
                message=str(exc),
            )
        write_result = self._cache_public_market_candles(
            exchange=request.exchange,
            symbol=request.symbol,
            timeframe=request.timeframe,
            candles=candles,
        )

        return HistoricalDataSyncResult(
            symbol=request.symbol,
            exchange=request.exchange,
            timeframe=request.timeframe,
            start_date=request.start_date,
            end_date=request.end_date,
            fetched=len(candles),
            inserted=write_result.inserted,
            updated=write_result.updated,
            first_timestamp=candles[0].timestamp if candles else None,
            last_timestamp=candles[-1].timestamp if candles else None,
            status="completed",
            message="Historical candles synced into local market_candles",
        )

    def get_ai_analysis(
        self,
        scope: str = "symbol",
        symbol: str | None = None,
        exchange: ExchangeId | None = None,
        refresh: bool = False,
        prefer_cached_snapshot: bool = False,
    ) -> AiAnalysis:
        resolved_scope = "market" if scope == "market" else "symbol"
        resolved_symbol = "MARKET" if resolved_scope == "market" else symbol or self.settings.default_symbol
        resolved_exchange = exchange or ExchangeId(self.settings.default_exchange)
        cache_key = (resolved_scope, resolved_symbol, resolved_exchange.value)

        cached = _AI_ANALYSIS_CACHE.get(cache_key)
        if not refresh and cached is not None and cached.expires_at > time.monotonic():
            return cached.value

        if prefer_cached_snapshot:
            snapshot = self._cached_ai_analysis_snapshot(
                scope=resolved_scope,
                symbol=resolved_symbol,
                exchange=resolved_exchange,
            )
            if snapshot is not None:
                return snapshot
            latest = self.ai_analysis_repository.get_latest_analysis()
            if latest is not None and self._ai_analysis_matches_target(
                latest,
                scope=resolved_scope,
                symbol=resolved_symbol,
                exchange=resolved_exchange,
            ):
                return latest
            return self._dashboard_ai_snapshot_unavailable(
                scope=resolved_scope,
                symbol=resolved_symbol,
                exchange=resolved_exchange,
            )

        news = self.get_news_sentiment(symbol=resolved_symbol)
        market_context = self._ai_market_context(
            scope=resolved_scope,
            symbol=resolved_symbol,
            exchange=resolved_exchange,
        )
        try:
            if news.article_count > 0 and hasattr(self.ai_service, "analyze_market_context"):
                analysis = self.ai_service.analyze_market_context(
                    news=news,
                    scope=resolved_scope,
                    market_context=market_context,
                )
            else:
                analysis = self.ai_service.analyze_empty_context(
                    scope=resolved_scope,
                    symbol=resolved_symbol,
                    market_context=market_context,
                )
        except AiServiceUnavailable as exc:
            analysis = self._ai_unavailable_fallback(
                news=news,
                exc=exc,
                scope=resolved_scope,
                market_context=market_context,
            )
        analysis = attach_ai_decision_signal(
            analysis,
            scope=resolved_scope,
            symbol=resolved_symbol,
            exchange=resolved_exchange,
            news=news,
            market_context=market_context,
        )
        _AI_ANALYSIS_CACHE[cache_key] = TimedCacheEntry(
            value=analysis,
            expires_at=time.monotonic() + max(1, self.settings.ai_analysis_cache_ttl_seconds),
        )
        return analysis

    def get_news_sentiment(
        self,
        symbol: str | None = None,
        limit: int | None = None,
        refresh: bool = False,
    ) -> NewsSentimentSummary:
        resolved_symbol = symbol or self.settings.default_symbol
        resolved_limit = max(1, min(limit or self.settings.news_default_limit, 50))
        cache_key = (resolved_symbol, resolved_limit)

        cached = _NEWS_SENTIMENT_CACHE.get(cache_key)
        if not refresh and cached is not None and cached.expires_at > time.monotonic():
            return cached.value

        summary = self.news_service.get_news_sentiment(symbol=resolved_symbol, limit=resolved_limit)
        _NEWS_SENTIMENT_CACHE[cache_key] = TimedCacheEntry(
            value=summary,
            expires_at=time.monotonic() + max(1, self.settings.news_cache_ttl_seconds),
        )
        if refresh:
            for key in list(_AI_ANALYSIS_CACHE):
                if key[1] == resolved_symbol:
                    _AI_ANALYSIS_CACHE.pop(key, None)
            self.audit_log_repository.append_log(
                AuditLog(
                    level=Severity.WARNING if summary.event_risk else Severity.INFO,
                    module="ai",
                    symbol=resolved_symbol,
                    message=(
                        "News sentiment refreshed: "
                        f"status={summary.status}, articles={summary.article_count}, "
                        f"score={summary.sentiment_score:.2f}, risk_level={summary.risk_level.value}"
                    ),
                    correlation_id=self._correlation_id("news"),
                ),
            )
        return summary

    def validate_ai_payload(self, payload: dict[str, object]) -> AiAnalysis:
        analysis = self.ai_service.validate_payload(payload)
        analysis = attach_ai_decision_signal(
            analysis,
            scope=analysis.analysis_scope,
            symbol=analysis.symbol or self.settings.default_symbol,
        )
        self.audit_log_repository.append_log(
            AuditLog(
                level=Severity.WARNING if analysis.event_risk else Severity.INFO,
                module="ai",
                message=f"AI structured payload validated with risk_level={analysis.risk_level.value}",
                correlation_id=self._correlation_id("ai"),
            ),
        )
        return analysis

    def _ai_unavailable_fallback(
        self,
        news: NewsSentimentSummary,
        exc: AiServiceUnavailable,
        scope: str = "symbol",
        market_context: dict[str, Any] | None = None,
    ) -> AiAnalysis:
        provider = getattr(self.ai_service, "provider", "ai_proxy")
        model = getattr(self.ai_service, "model", "unknown")
        news_rationale = news.rationale[:5] if news.rationale else []
        reason = self._public_exception(exc)
        return AiAnalysis(
            analysis_scope=scope,
            symbol=news.symbol,
            market_regime=(
                f"ai_unavailable_news_{news.sentiment_label.value}"
                if news.article_count
                else "ai_unavailable"
            ),
            sentiment_score=news.sentiment_score,
            risk_level=RiskLevel.HIGH,
            event_risk=True,
            allowed_direction=AllowedDirection.NONE,
            confidence=0,
            provider=provider,
            model=model,
            rationale=[
                f"AI proxy unavailable, conservative fallback applied: {reason}",
                *news_rationale,
            ],
            structured_payload={
                "market_regime": "ai_unavailable",
                "sentiment_score": news.sentiment_score,
                "risk_level": RiskLevel.HIGH.value,
                "event_risk": True,
                "allowed_direction": AllowedDirection.NONE.value,
                "confidence": 0,
                "analysis_scope": scope,
                "symbol": news.symbol,
                "fallback_reason": reason,
                "market_context": market_context,
                "news": {
                    "status": news.status,
                    "article_count": news.article_count,
                    "source_count": news.source_count,
                    "sentiment_label": news.sentiment_label.value,
                    "top_headlines": [article.title for article in news.articles[:5]],
                },
            },
        )

    def _ai_market_context(
        self,
        scope: str,
        symbol: str,
        exchange: ExchangeId | None = None,
    ) -> dict[str, Any]:
        exchange = exchange or ExchangeId(self.settings.default_exchange)
        timeframe = self.settings.default_timeframe
        symbols = (
            MARKET_ANALYSIS_SYMBOLS_BY_EXCHANGE.get(exchange, (self.settings.default_symbol,))
            if scope == "market"
            else (symbol,)
        )
        snapshots: list[dict[str, Any]] = []

        for item in symbols:
            market = self.get_market_overview(
                symbol=item,
                timeframe=timeframe,
                exchange=exchange,
                limit=120,
                refresh=False,
                allow_stale_local=True,
            )
            snapshots.append(
                {
                    "symbol": market.symbol,
                    "exchange": market.exchange.value,
                    "timeframe": market.timeframe,
                    "last_price": market.last_price,
                    "change_24h_percent": market.change_24h_percent,
                    "volume_24h": market.volume_24h,
                    "volatility": market.volatility,
                    "rsi": market.rsi,
                    "data_latency_seconds": market.data_latency_seconds,
                    "data_integrity": market.data_integrity,
                },
            )

        return {
            "scope": scope,
            "symbol": symbol,
            "exchange": exchange.value,
            "timeframe": timeframe,
            "snapshots": snapshots,
        }

    def get_trading_summary(self) -> TradingSummary:
        portfolio = self._current_portfolio_context(include_open_orders=True)
        historical_orders = self.portfolio_repository.list_historical_orders(limit=100)

        return TradingSummary(
            mode=self.get_system_status().trading_mode,
            balances=portfolio.balances,
            positions=portfolio.positions,
            open_orders=portfolio.open_orders,
            historical_orders=historical_orders,
        )

    def _current_portfolio_context(self, include_open_orders: bool = True) -> PortfolioContext:
        balances = self.portfolio_repository.list_balances()
        positions = self.portfolio_repository.list_positions()
        open_orders = self.portfolio_repository.list_open_orders() if include_open_orders else []

        live_snapshot = self._fetch_live_portfolio_snapshot(include_open_orders=include_open_orders)
        if live_snapshot is None:
            return PortfolioContext(
                balances=balances,
                positions=positions,
                open_orders=open_orders,
                source="local",
            )

        live_balances, live_positions, live_open_orders = live_snapshot
        live_exchanges = {order.exchange for order in live_open_orders}
        merged_open_orders = [
            *live_open_orders,
            *[order for order in open_orders if order.exchange not in live_exchanges],
        ]
        return PortfolioContext(
            balances=live_balances,
            positions=live_positions,
            open_orders=merged_open_orders,
            source="live",
        )

    def _fetch_live_portfolio_snapshot(
        self,
        include_open_orders: bool = True,
    ) -> tuple[list[Balance], list[Position], list[Order]] | None:
        configured = self._configured_private_exchanges()
        if not configured:
            return None

        cache_key = (
            *[exchange.value for exchange in configured],
            "with_open_orders" if include_open_orders else "balances_only",
        )
        cached = _PORTFOLIO_SNAPSHOT_CACHE.get(cache_key)
        now = time.monotonic()
        if cached is not None and cached.expires_at > now:
            return cached.value

        balances: list[Balance] = []
        positions: list[Position] = []
        open_orders: list[Order] = []
        any_success = False

        for exchange in configured:
            try:
                client = get_spot_trading_client(exchange, self.settings)
                exchange_balances = self._call_private_exchange_with_timeout(
                    exchange=exchange,
                    scope="balances",
                    operation=client.get_balances,
                )
            except AttributeError:
                continue
            except (ExchangeTradingError, ExchangeTradingNotConfiguredError) as exc:
                self._record_live_portfolio_failure(exchange, "balances", exc)
                continue

            any_success = True
            balances.extend(exchange_balances)
            positions.extend(self._derive_spot_positions(exchange, exchange_balances))

            if include_open_orders:
                try:
                    exchange_open_orders = self._call_private_exchange_with_timeout(
                        exchange=exchange,
                        scope="open_orders",
                        operation=client.get_open_orders,
                    )
                except (ExchangeTradingError, ExchangeTradingNotConfiguredError, AttributeError) as exc:
                    self._record_live_portfolio_failure(exchange, "open_orders", exc)
                    exchange_open_orders = []
                open_orders.extend(exchange_open_orders)

        if not any_success:
            return None

        snapshot = (balances, positions, open_orders)
        _PORTFOLIO_SNAPSHOT_CACHE[cache_key] = TimedCacheEntry(
            value=snapshot,
            expires_at=now + max(5, self.settings.public_market_cache_ttl_seconds),
        )
        return snapshot

    def _call_private_exchange_with_timeout(
        self,
        exchange: ExchangeId,
        scope: str,
        operation: Callable[[], T],
    ) -> T:
        timeout_seconds = self._private_exchange_request_timeout_seconds()
        future = _LIVE_PORTFOLIO_EXECUTOR.submit(operation)
        try:
            return future.result(timeout=timeout_seconds)
        except FutureTimeoutError as exc:
            future.cancel()
            raise ExchangeTradingError(
                f"{exchange.value} private {scope} request timed out after {timeout_seconds:g}s",
            ) from exc

    def _private_exchange_request_timeout_seconds(self) -> float:
        return min(max(float(self.settings.exchange_api_timeout_seconds), 1.0) + 1.0, 10.0)

    def _configured_private_exchanges(self) -> list[ExchangeId]:
        configured: list[ExchangeId] = []
        if self.settings.binance_api_key and self.settings.binance_api_secret:
            configured.append(ExchangeId.BINANCE)
        if (
            self.settings.okx_api_key
            and self.settings.okx_api_secret
            and self.settings.okx_api_passphrase
        ):
            configured.append(ExchangeId.OKX)
        return configured

    def _derive_spot_positions(
        self,
        exchange: ExchangeId,
        balances: list[Balance],
    ) -> list[Position]:
        position_balances = [
            balance
            for balance in balances
            if balance.asset.upper() not in STABLE_QUOTE_ASSETS and balance.total > 0
        ]
        symbols = [f"{balance.asset.upper()}/USDT" for balance in position_balances]
        prices = self._safe_spot_prices(exchange, symbols)
        positions: list[Position] = []
        for balance in position_balances:
            asset = balance.asset.upper()
            symbol = f"{asset}/USDT"
            current_price = prices.get(symbol)
            if current_price is None:
                current_price = 0
            positions.append(
                Position(
                    symbol=symbol,
                    side="long",
                    quantity=balance.total,
                    average_price=current_price,
                    current_price=current_price,
                    unrealized_pnl=0,
                ),
        )
        return positions

    def _safe_spot_prices(self, exchange: ExchangeId, symbols: list[str]) -> dict[str, float | None]:
        unique_symbols = list(dict.fromkeys(symbols))
        if not unique_symbols:
            return {}

        timeout_seconds = self._private_exchange_request_timeout_seconds()
        deadline = time.monotonic() + timeout_seconds
        futures = {
            symbol: _LIVE_PORTFOLIO_EXECUTOR.submit(self._safe_spot_price, exchange, symbol)
            for symbol in unique_symbols
        }
        prices: dict[str, float | None] = {}
        for symbol, future in futures.items():
            remaining_seconds = max(0.01, deadline - time.monotonic())
            try:
                prices[symbol] = future.result(timeout=remaining_seconds)
            except FutureTimeoutError:
                future.cancel()
                prices[symbol] = None
        return prices

    def _safe_spot_price(self, exchange: ExchangeId, symbol: str) -> float | None:
        try:
            overview = self.get_market_overview(
                symbol=symbol,
                timeframe=self.settings.default_timeframe,
                exchange=exchange,
                limit=50,
                refresh=False,
                allow_stale_local=True,
            )
        except (ExchangeMarketDataError, ExchangeTradingError, ValueError, KeyError):
            return None
        return overview.last_price if overview and overview.last_price else None

    def _portfolio_equity(self, balances: list[Balance], positions: list[Position]) -> float:
        stable_value = sum(balance.total for balance in balances if balance.asset.upper() in STABLE_QUOTE_ASSETS)
        position_value = sum(max(position.quantity * position.current_price, 0) for position in positions)
        return max(stable_value + position_value, 0)

    def _record_live_portfolio_failure(
        self,
        exchange: ExchangeId,
        scope: str,
        exc: Exception,
    ) -> None:
        try:
            self.audit_log_repository.append_log(
                AuditLog(
                    level=Severity.WARNING,
                    module="trading",
                    message=(
                        f"Live portfolio {scope} fetch failed for {exchange.value}: "
                        f"{self._public_exchange_account_error(exc)}"
                    ),
                    correlation_id=self._correlation_id("portfolio"),
                ),
            )
        except Exception:  # noqa: BLE001 - audit logging must not block the response.
            pass

    def get_risk_status(
        self,
        ai: AiAnalysis | None = None,
        correlation_id: str | None = None,
        balances: list[Balance] | None = None,
        positions: list[Position] | None = None,
    ) -> RiskStatusResponse:
        persisted_events = self.risk_repository.list_events(limit=100)
        market = self._risk_market_context()
        state = self.system_state_repository.get_state()
        if balances is None or positions is None:
            portfolio = self._current_portfolio_context(include_open_orders=False)
            balances = portfolio.balances
            positions = portfolio.positions
        response = self.risk_engine.evaluate(
            balances=balances,
            positions=positions,
            ai=ai or self._risk_ai_snapshot(),
            persisted_rules=self.risk_repository.list_rules(),
            historical_orders=self.portfolio_repository.list_historical_orders(limit=50),
            data_latency_seconds=market.data_latency_seconds,
            data_integrity=market.data_integrity,
            paused=state.paused,
            kill_switch_armed=state.kill_switch_armed,
            thresholds=RiskThresholds(
                max_data_latency_seconds=self.settings.max_data_latency_seconds,
            ),
            correlation_id=correlation_id or self._correlation_id("risk"),
        )
        return response.model_copy(update={"events": [*response.events, *persisted_events][:100]})

    def _risk_ai_snapshot(self) -> AiAnalysis:
        cached = self._cached_ai_analysis_snapshot()
        if cached is not None:
            return cached

        latest = self.ai_analysis_repository.get_latest_analysis()
        if latest is not None:
            return latest

        symbol = self.settings.default_symbol
        return AiAnalysis(
            analysis_scope="symbol",
            symbol=symbol,
            market_regime="ai_snapshot_unavailable",
            sentiment_score=0,
            risk_level=RiskLevel.HIGH,
            event_risk=True,
            allowed_direction=AllowedDirection.NONE,
            confidence=0,
            provider="local_risk_fallback",
            model="snapshot-unavailable",
            rationale=[
                "No cached AI analysis snapshot is available; risk status used a conservative local fallback.",
            ],
            structured_payload={
                "analysis_scope": "symbol",
                "symbol": symbol,
                "fallback_reason": "ai_snapshot_unavailable",
            },
        )

    def _cached_ai_analysis_snapshot(
        self,
        scope: str | None = None,
        symbol: str | None = None,
        exchange: ExchangeId | None = None,
    ) -> AiAnalysis | None:
        now = time.monotonic()
        if scope is not None or symbol is not None or exchange is not None:
            resolved_scope = "market" if scope == "market" else "symbol"
            resolved_symbol = (
                "MARKET" if resolved_scope == "market" else symbol or self.settings.default_symbol
            )
            resolved_exchange = exchange or ExchangeId(self.settings.default_exchange)
            cache_key = (resolved_scope, resolved_symbol, resolved_exchange.value)
            cached = _AI_ANALYSIS_CACHE.get(cache_key)
            if cached is not None:
                if cached.expires_at > now:
                    return cached.value
                _AI_ANALYSIS_CACHE.pop(cache_key, None)
            return None

        preferred_key = ("symbol", self.settings.default_symbol, self.settings.default_exchange)
        preferred = _AI_ANALYSIS_CACHE.get(preferred_key)
        if preferred is not None:
            if preferred.expires_at > now:
                return preferred.value
            _AI_ANALYSIS_CACHE.pop(preferred_key, None)

        for key, cached in list(_AI_ANALYSIS_CACHE.items()):
            if cached.expires_at <= now:
                _AI_ANALYSIS_CACHE.pop(key, None)
                continue
            return cached.value

        return None

    @staticmethod
    def _ai_analysis_matches_target(
        analysis: AiAnalysis,
        *,
        scope: str,
        symbol: str,
        exchange: ExchangeId | None = None,
    ) -> bool:
        expected_scope = "market" if scope == "market" else "symbol"
        expected_symbol = "MARKET" if expected_scope == "market" else symbol
        payload = analysis.structured_payload or {}
        payload_scope = payload.get("analysis_scope")
        payload_symbol = payload.get("symbol")
        analysis_scope = payload_scope if isinstance(payload_scope, str) else analysis.analysis_scope
        analysis_symbol = payload_symbol if isinstance(payload_symbol, str) else analysis.symbol
        if analysis_scope != expected_scope or analysis_symbol != expected_symbol:
            return False
        if exchange is None:
            return True
        signal_exchange = analysis.decision_signal.exchange if analysis.decision_signal else None
        payload_exchange = payload.get("exchange")
        return signal_exchange in {None, exchange} and payload_exchange in {None, exchange.value}

    def create_dry_run_order(self, request: DryRunOrderRequest) -> Order:
        correlation_id = self._correlation_id("decision")
        positions = self.portfolio_repository.list_positions()
        signal = self._build_order_signal(request, correlation_id)
        strategy = request.strategy or "manual"
        self.audit_log_repository.append_log(
            AuditLog(
                level=Severity.INFO,
                module="strategy",
                symbol=request.symbol,
                strategy=strategy,
                message=f"Strategy signal captured: action={request.action.value}, quantity={request.quantity:g}",
                correlation_id=correlation_id,
            ),
        )
        ai = self.get_ai_analysis().model_copy(update={"correlation_id": correlation_id})
        self.ai_analysis_repository.save_analysis(ai)
        self.audit_log_repository.append_log(
            AuditLog(
                level=Severity.WARNING if ai.risk_level.value in {"high", "extreme"} else Severity.INFO,
                module="ai",
                symbol=request.symbol,
                strategy=request.strategy,
                message=(
                    "AI filter snapshot captured: "
                    f"risk_level={ai.risk_level.value}, "
                    f"allowed_direction={ai.allowed_direction.value}, "
                    f"confidence={ai.confidence:.2f}, provider={ai.provider}, model={ai.model}"
                ),
                correlation_id=correlation_id,
            ),
        )
        risk = self.get_risk_status(ai=ai, correlation_id=correlation_id)
        order = self.trading_service.validate_order(request=request, positions=positions, risk=risk)
        blocked_by = self._signal_blocker(order.status, risk.status, ai)
        if blocked_by is not None:
            signal = signal.model_copy(update={"blocked_by": blocked_by})
        self.strategy_repository.append_signal(signal)

        saved = self.portfolio_repository.save_order(order.model_copy(update={"correlation_id": correlation_id}))
        persisted_risk_events = self._persist_order_risk_events(saved, risk.events)
        self.audit_log_repository.append_log(
            AuditLog(
                level=Severity.WARNING if saved.status.startswith("rejected") else Severity.INFO,
                module="trading",
                symbol=request.symbol,
                strategy=request.strategy,
                message=(
                    f"Dry-run spot order validation result: {saved.status}; "
                    f"risk_events={len(persisted_risk_events)}"
                ),
                correlation_id=correlation_id,
            ),
        )
        return saved

    def create_live_order(self, request: LiveOrderRequest) -> Order:
        exchange = request.exchange or ExchangeId(self.settings.default_exchange)
        self._assert_live_trading_ready(exchange)
        side = self._spot_order_side(request.action)
        correlation_id = self._correlation_id("live")
        dry_run_request = DryRunOrderRequest(
            symbol=request.symbol,
            action=request.action,
            order_type=request.order_type,
            quantity=request.quantity,
            price=request.price,
            strategy=request.strategy,
        )
        positions = self.portfolio_repository.list_positions()
        signal = self._build_order_signal(dry_run_request, correlation_id)
        strategy = request.strategy or "manual"
        self.audit_log_repository.append_log(
            AuditLog(
                level=Severity.WARNING,
                module="strategy",
                symbol=request.symbol,
                strategy=strategy,
                message=(
                    "Live strategy signal captured: "
                    f"exchange={exchange.value}, action={request.action.value}, quantity={request.quantity:g}"
                ),
                correlation_id=correlation_id,
            ),
        )

        ai = self.get_ai_analysis().model_copy(update={"correlation_id": correlation_id})
        self.ai_analysis_repository.save_analysis(ai)
        risk = self.get_risk_status(ai=ai, correlation_id=correlation_id)
        validation = self.trading_service.validate_order(
            request=dry_run_request,
            positions=positions,
            risk=risk,
        )
        blocked_by = self._signal_blocker(validation.status, risk.status, ai)
        if blocked_by is not None:
            signal = signal.model_copy(update={"blocked_by": blocked_by})
        self.strategy_repository.append_signal(signal)

        if not validation.status.startswith("validated"):
            saved = self.portfolio_repository.save_order(
                validation.model_copy(
                    update={
                        "exchange": exchange,
                        "correlation_id": correlation_id,
                        "order_id": validation.order_id.replace("DRY-", "LIVE-REJECTED-", 1),
                    },
                ),
            )
            persisted_risk_events = self._persist_order_risk_events(saved, risk.events)
            self.audit_log_repository.append_log(
                AuditLog(
                    level=Severity.WARNING,
                    module="trading",
                    symbol=request.symbol,
                    strategy=request.strategy,
                    message=(
                        f"Live spot order blocked before exchange submit: {saved.status}; "
                        f"risk_events={len(persisted_risk_events)}"
                    ),
                    correlation_id=correlation_id,
                ),
            )
            return saved

        try:
            exchange_order = get_spot_trading_client(exchange, self.settings).create_order(
                SpotOrderRequest(
                    symbol=request.symbol,
                    side=side,
                    order_type=request.order_type,
                    quantity=request.quantity,
                    price=request.price,
                    client_order_id=request.client_order_id or correlation_id,
                ),
            )
        except (ExchangeTradingError, ExchangeTradingNotConfiguredError) as exc:
            rejected = self.portfolio_repository.save_order(
                Order(
                    exchange=exchange,
                    order_id=f"LIVE-FAILED-{int(utc_now().timestamp() * 1000)}",
                    correlation_id=correlation_id,
                    symbol=request.symbol,
                    side=side,
                    order_type=request.order_type,
                    price=request.price or 0,
                    quantity=request.quantity,
                    status="exchange_error",
                    created_at=utc_now(),
                ),
            )
            self.audit_log_repository.append_log(
                AuditLog(
                    level=Severity.CRITICAL,
                    module="trading",
                    symbol=request.symbol,
                    strategy=request.strategy,
                    message=f"Live spot order exchange submit failed: {self._public_exception(exc)}",
                    correlation_id=correlation_id,
                ),
            )
            return rejected

        saved = self.portfolio_repository.save_order(
            exchange_order.model_copy(update={"exchange": exchange, "correlation_id": correlation_id}),
        )
        self.audit_log_repository.append_log(
            AuditLog(
                level=Severity.CRITICAL,
                module="trading",
                symbol=request.symbol,
                strategy=request.strategy,
                message=(
                    f"Live spot order submitted: exchange={exchange.value}, "
                    f"order_id={saved.order_id}, status={saved.status}"
                ),
                correlation_id=correlation_id,
            ),
        )
        return saved

    def cancel_live_order(self, request: LiveCancelOrderRequest) -> Order:
        exchange = request.exchange or ExchangeId(self.settings.default_exchange)
        correlation_id = self._correlation_id("cancel")
        self._assert_live_trading_ready(exchange, allow_management=True)
        try:
            canceled = get_spot_trading_client(exchange, self.settings).cancel_order(
                symbol=request.symbol,
                order_id=request.order_id,
            )
        except (ExchangeTradingError, ExchangeTradingNotConfiguredError) as exc:
            failed = self.portfolio_repository.save_order(
                Order(
                    exchange=exchange,
                    order_id=request.order_id,
                    correlation_id=correlation_id,
                    symbol=request.symbol,
                    side=SpotSignalAction.CANCEL_ORDER.value,
                    order_type="cancel",
                    price=0,
                    quantity=0,
                    status="exchange_error",
                    created_at=utc_now(),
                ),
            )
            self.audit_log_repository.append_log(
                AuditLog(
                    level=Severity.CRITICAL,
                    module="trading",
                    symbol=request.symbol,
                    message=f"Live spot cancel failed: {self._public_exception(exc)}",
                    correlation_id=correlation_id,
                ),
            )
            return failed

        saved = self.portfolio_repository.save_order(
            canceled.model_copy(
                update={
                    "exchange": exchange,
                    "correlation_id": correlation_id,
                    "symbol": request.symbol,
                    "side": SpotSignalAction.CANCEL_ORDER.value,
                    "order_type": "cancel",
                    "status": canceled.status if canceled.status != "submitted" else "canceled",
                },
            ),
        )
        self.audit_log_repository.append_log(
            AuditLog(
                level=Severity.WARNING,
                module="trading",
                symbol=request.symbol,
                message=f"Live spot order canceled: exchange={exchange.value}, order_id={request.order_id}",
                correlation_id=correlation_id,
            ),
        )
        return saved

    def close_live_position(self, request: ManualClosePositionRequest) -> Order:
        exchange = request.exchange or ExchangeId(self.settings.default_exchange)
        positions = self.portfolio_repository.list_positions()
        position = next((item for item in positions if item.symbol == request.symbol), None)
        if position is None:
            raise ValueError(f"No local spot position found for {request.symbol}")
        quantity = request.quantity or position.quantity
        if quantity > position.quantity:
            raise ValueError(f"Close quantity exceeds local spot position for {request.symbol}")

        return self.create_live_order(
            LiveOrderRequest(
                exchange=exchange,
                symbol=request.symbol,
                action=SpotSignalAction.SELL_EXISTING,
                order_type=request.order_type,
                quantity=quantity,
                price=request.price,
                strategy="manual_close",
            ),
        )

    def get_trade_decision_trace(self, correlation_id: str) -> TradeDecisionTrace:
        return TradeDecisionTrace(
            correlation_id=correlation_id,
            signal=self.strategy_repository.get_signal_by_correlation_id(correlation_id),
            ai_analysis=self.ai_analysis_repository.get_analysis_by_correlation_id(correlation_id),
            risk_status=self._risk_status_from_trace_events(correlation_id),
            risk_events=self.risk_repository.list_events_by_correlation_id(correlation_id, limit=100),
            order=self.portfolio_repository.get_order_by_correlation_id(correlation_id),
            logs=self.audit_log_repository.list_logs_by_correlation_id(correlation_id, limit=100),
        )

    def send_test_notification(self, request: NotificationTestRequest) -> NotificationResult:
        result = self.notification_service.send_test(request)
        self.audit_log_repository.append_log(
            AuditLog(
                level=Severity.SUCCESS if result.success else Severity.WARNING,
                module="notification",
                message=f"{result.provider} notification test result: {result.message}",
                correlation_id=self._correlation_id("notice"),
            ),
        )
        return result

    def send_daily_push(self) -> DailyPushResult:
        title, message = self.build_daily_push_report()
        results = self.notification_service.send_to_configured_channels(
            title=title,
            message=message,
        )
        success = any(result.success for result in results)
        provider_summary = ", ".join(
            f"{result.provider}:{'ok' if result.success else result.message}"
            for result in results
        )
        self.audit_log_repository.append_log(
            AuditLog(
                level=Severity.SUCCESS if success else Severity.WARNING,
                module="notification",
                message=f"Daily push result: {provider_summary}",
                correlation_id=self._correlation_id("daily-push"),
            ),
        )
        return DailyPushResult(success=success, title=title, message=message, results=results)

    def build_daily_push_report(self) -> tuple[str, str]:
        now = datetime.now()
        generated_at = now.strftime("%Y-%m-%d %H:%M:%S")
        symbol = self.settings.default_symbol
        exchange = ExchangeId(self.settings.default_exchange)
        title = f"🎯 SpotPilot Quant 每日量化日报 - {now.strftime('%Y-%m-%d')}"

        dashboard = self.get_dashboard(refresh=True)
        market = self.get_market_overview(
            symbol=symbol,
            timeframe=self.settings.default_timeframe,
            exchange=exchange,
            limit=120,
            refresh=True,
            allow_stale_local=True,
        )
        risk_metric = next(
            (metric for metric in dashboard.metrics if metric.label == "风控状态"),
            None,
        )
        metrics = {metric.label: metric for metric in dashboard.metrics}
        net_equity = metrics.get("资产净值")
        daily_pnl = metrics.get("今日盈亏")
        position_count = metrics.get("当前仓位")
        risk_value = risk_metric.value if risk_metric else "unknown"

        decision_lines = self._daily_push_decision_lines(
            ai=dashboard.ai,
            risk_metric=risk_metric,
            market=market,
        )
        position_lines = self._daily_push_position_lines(dashboard.positions)
        signal_lines = self._daily_push_signal_lines(dashboard.latest_signals)
        alert_lines = self._daily_push_alert_lines(dashboard.latest_logs)
        rationale_lines = self._daily_push_rationale_lines(dashboard.ai.rationale)

        body_lines = [
            f"🕒 生成时间: {generated_at}",
            f"📌 分析标的: {symbol} / {exchange.value} / {self.settings.default_timeframe}",
            "",
            "🎯 今日结论",
            *decision_lines,
            "",
            "📊 行情与 AI",
            (
                f"- 价格: {self._format_price(market.last_price)} | 24h "
                f"{self._format_signed_percent(market.change_24h_percent)}，"
                f"RSI {self._format_ratio(market.rsi)}，波动 "
                f"{self._format_percent(market.volatility)}"
            ),
            (
                f"- AI: {self._market_regime_label(dashboard.ai.market_regime)}；"
                f"风险 {self._risk_level_label(dashboard.ai.risk_level.value)}；"
                f"方向 {self._allowed_direction_label(dashboard.ai.allowed_direction.value)}；"
                f"置信度 {self._format_ratio(dashboard.ai.confidence)}"
            ),
            f"- 数据: {self._market_integrity_label(market.data_integrity)}",
            *rationale_lines,
            "",
            "💼 账户与仓位",
            (
                f"- 净值: {net_equity.value if net_equity else 'N/A'} | "
                f"今日盈亏 {daily_pnl.value if daily_pnl else 'N/A'}；"
                f"持仓 {position_count.value if position_count else str(len(dashboard.positions))}；"
                f"风控 {self._status_dot_for_risk(str(risk_value))} "
                f"{self._risk_status_label(str(risk_value))}"
            ),
            f"- 风控说明: {self._trim_text(risk_metric.detail, 90) if risk_metric else '暂无'}",
            *position_lines,
            "",
            "📡 策略信号",
            *signal_lines,
            "",
            "🔔 系统提醒",
            *alert_lines,
        ]
        return title, "\n".join(body_lines)

    def _daily_push_decision_lines(
        self,
        *,
        ai: AiAnalysis,
        risk_metric: Metric | None,
        market: MarketOverview,
    ) -> list[str]:
        lines: list[str] = []
        risk_value = risk_metric.value if risk_metric else "unknown"
        if str(risk_value).lower() in {"paused", "no_new_positions", "reduce_only"}:
            lines.append(
                f"- {self._status_dot_for_risk(str(risk_value))} "
                f"风控处于 {self._risk_status_label(str(risk_value))}，先暂停所有新开仓动作。",
            )
        elif ai.allowed_direction.value == AllowedDirection.NONE.value:
            lines.append("- 🔴 AI 当前不允许开仓，优先观察而不是追单。")
        else:
            lines.append(
                "- 🟢 风控未阻断交易，"
                f"允许方向为 {self._allowed_direction_label(ai.allowed_direction.value)}。",
            )

        if ai.confidence <= 0 or "unavailable" in ai.market_regime:
            lines.append("- 🟡 AI 模型通道不可用或置信度不足，本次结论按保守模式处理。")
        elif ai.event_risk:
            lines.append("- 🟡 新闻或事件风险已触发，仓位动作需要人工确认。")
        else:
            lines.append(
                f"- {self._status_dot_for_ai(ai.risk_level.value)} "
                f"AI 风险为 {self._risk_level_label(ai.risk_level.value)}，"
                f"置信度 {self._format_ratio(ai.confidence)}。",
            )

        direction = "偏弱" if market.change_24h_percent < 0 else "偏强"
        market_dot = "🔴" if market.change_24h_percent < 0 else "🟢"
        lines.append(
            f"- {market_dot} {market.symbol} 24h {direction} "
            f"({self._format_signed_percent(market.change_24h_percent)})，"
            f"RSI {self._format_ratio(market.rsi)}。",
        )
        return lines

    def _daily_push_position_lines(self, positions: list[Position]) -> list[str]:
        if not positions:
            return ["- 暂无现货持仓。"]

        sorted_positions = sorted(
            positions,
            key=lambda item: abs(item.quantity * item.current_price),
            reverse=True,
        )
        lines = ["- 主要持仓:"]
        for index, position in enumerate(sorted_positions[:5], start=1):
            market_value = position.quantity * position.current_price
            lines.append(
                f"  {index}. {position.symbol}: 数量 {self._format_quantity(position.quantity)}，"
                f"现价 {self._format_price(position.current_price)}，"
                f"市值 {self._format_money(market_value)}，"
                f"浮盈 {self._format_money(position.unrealized_pnl)}"
            )
        if len(sorted_positions) > 5:
            lines.append(f"- 另有 {len(sorted_positions) - 5} 个小仓位未展开。")
        return lines

    def _daily_push_signal_lines(self, signals: list[StrategySignal]) -> list[str]:
        useful_lines: list[str] = []
        seen: set[tuple[str, str, str, str]] = set()
        skipped = 0

        for signal in signals:
            reason = signal.reason.strip()
            if reason.lower().startswith("dry-run order request received"):
                skipped += 1
                continue
            dedupe_key = (
                signal.symbol,
                signal.strategy,
                signal.action.value,
                reason[:80],
            )
            if dedupe_key in seen:
                skipped += 1
                continue
            seen.add(dedupe_key)
            useful_lines.append(
                f"- {self._signal_icon(signal.action.value)} {signal.symbol} / {signal.strategy}: "
                f"{self._signal_action_label(signal.action.value)}，"
                f"价格 {self._format_price(signal.price)}；"
                f"{self._trim_text(reason, 70)}"
            )
            if len(useful_lines) >= 5:
                break

        if not useful_lines:
            useful_lines.append("- 暂无新的有效策略信号。")
        if skipped:
            useful_lines.append(f"- 已折叠 {skipped} 条重复或手动干跑信号。")
        return useful_lines

    def _daily_push_alert_lines(self, logs: list[AuditLog]) -> list[str]:
        lines: list[str] = []
        seen: set[str] = set()

        for log in logs:
            if log.module == "notification" and "Daily push result" in log.message:
                continue
            if log.level not in {Severity.WARNING, Severity.CRITICAL}:
                continue
            message = self._human_log_message(log.message)
            dedupe_key = f"{log.level.value}:{log.module}:{message}"
            if dedupe_key in seen:
                continue
            seen.add(dedupe_key)
            lines.append(
                f"- {self._severity_icon(log.level.value)} {self._severity_label(log.level.value)} / "
                f"{self._module_label(log.module)}: {message}"
            )
            if len(lines) >= 3:
                break

        return lines or ["- ✅ 暂无需要处理的系统告警。"]

    def _daily_push_rationale_lines(self, rationale: list[str]) -> list[str]:
        lines: list[str] = []
        for item in rationale:
            text = self._human_ai_rationale(item)
            if text and text not in lines:
                lines.append(text)
            if len(lines) >= 3:
                break
        return [f"- 🧠 关注: {line}" for line in lines] if lines else ["- 🧠 关注: 暂无可解释摘要。"]

    @staticmethod
    def _trim_text(value: str, max_length: int) -> str:
        text = " ".join(str(value).split())
        if len(text) <= max_length:
            return text
        return text[: max_length - 3].rstrip() + "..."

    @classmethod
    def _human_ai_rationale(cls, value: str) -> str:
        text = cls._trim_text(value, 120)
        lower = text.lower()
        if "ai proxy unavailable" in lower or "all ai proxies unavailable" in lower:
            return "AI 模型通道超时或不可用，系统已切换为保守降级结论。"
        if "market data context included" in lower:
            return "行情快照已纳入分析，当前结论会受数据完整度影响。"
        if lower.startswith("news sentiment"):
            return text.replace("News sentiment", "新闻情绪")
        return text

    @classmethod
    def _human_log_message(cls, value: str) -> str:
        lower = value.lower()
        if "fetch_open_orders failed" in lower:
            return "交易所挂单查询失败，挂单数据可能不完整；余额和持仓快照仍可参考。"
        return cls._trim_text(value, 120)

    @staticmethod
    def _strip_number(value: str) -> str:
        if "." not in value:
            return value
        return value.rstrip("0").rstrip(".")

    @classmethod
    def _format_decimal(cls, value: float, *, large_decimals: int = 2, small_decimals: int = 8) -> str:
        if not math.isfinite(value):
            return "N/A"
        abs_value = abs(value)
        if abs_value >= 1000:
            return cls._strip_number(f"{value:,.{large_decimals}f}")
        if abs_value >= 1:
            return cls._strip_number(f"{value:.4f}")
        if abs_value == 0:
            return "0"
        return cls._strip_number(f"{value:.{small_decimals}f}")

    @classmethod
    def _format_price(cls, value: float) -> str:
        return cls._format_decimal(value, large_decimals=2, small_decimals=8)

    @classmethod
    def _format_quantity(cls, value: float) -> str:
        return cls._format_decimal(value, large_decimals=4, small_decimals=8)

    @classmethod
    def _format_money(cls, value: float) -> str:
        return f"${cls._format_decimal(value, large_decimals=2, small_decimals=6)}"

    @staticmethod
    def _format_ratio(value: float) -> str:
        if not math.isfinite(value):
            return "N/A"
        return f"{value:.2f}"

    @staticmethod
    def _format_percent(value: float) -> str:
        if not math.isfinite(value):
            return "N/A"
        return f"{value:.2f}%"

    @staticmethod
    def _format_signed_percent(value: float) -> str:
        if not math.isfinite(value):
            return "N/A"
        return f"{value:+.2f}%"

    @staticmethod
    def _risk_status_label(value: str) -> str:
        return {
            "allow_trading": "允许交易",
            "reduce_only": "仅允许减仓",
            "no_new_positions": "禁止新开仓",
            "paused": "已暂停",
        }.get(value, value)

    @staticmethod
    def _risk_level_label(value: str) -> str:
        return {
            "low": "低",
            "medium": "中",
            "high": "高",
            "extreme": "极高",
        }.get(value, value)

    @staticmethod
    def _allowed_direction_label(value: str) -> str:
        return {
            "long_only": "只做多",
            "reduce_only": "只减仓",
            "both": "双向观察",
            "none": "禁止开仓",
        }.get(value, value)

    @staticmethod
    def _signal_action_label(value: str) -> str:
        return {
            "buy": "买入",
            "sell_existing": "卖出现有仓位",
            "hold": "继续观察",
            "cancel_order": "撤单",
        }.get(value, value)

    @staticmethod
    def _signal_icon(value: str) -> str:
        return {
            "buy": "🟢",
            "sell_existing": "🔴",
            "hold": "🟡",
            "cancel_order": "⚪",
        }.get(value, "📌")

    @staticmethod
    def _status_dot_for_risk(value: str) -> str:
        return {
            "allow_trading": "🟢",
            "reduce_only": "🟡",
            "no_new_positions": "🟡",
            "paused": "🔴",
        }.get(value, "⚪")

    @staticmethod
    def _status_dot_for_ai(value: str) -> str:
        return {
            "low": "🟢",
            "medium": "🟡",
            "high": "🔴",
            "extreme": "🔴",
        }.get(value, "⚪")

    @staticmethod
    def _severity_icon(value: str) -> str:
        return {
            "warning": "🟡",
            "critical": "🔴",
            "success": "🟢",
            "info": "🔵",
        }.get(value, "⚪")

    @staticmethod
    def _severity_label(value: str) -> str:
        return {
            "warning": "告警",
            "critical": "严重",
            "success": "成功",
            "info": "信息",
        }.get(value, value)

    @staticmethod
    def _module_label(value: str) -> str:
        return {
            "trading": "交易",
            "risk": "风控",
            "notification": "通知",
            "ai": "AI",
            "system": "系统",
            "strategy": "策略",
        }.get(value, value)

    @staticmethod
    def _market_integrity_label(value: str) -> str:
        if value == "live_public":
            return "交易所实时公共行情"
        if value == "empty":
            return "暂无可用行情"
        if value.startswith("exchange_error"):
            return "交易所行情异常，已使用可用降级数据"
        if value == "local_cache_empty":
            return "本地缓存暂无行情"
        return value

    @staticmethod
    def _market_regime_label(value: str) -> str:
        labels = {
            "ai_unavailable_news_neutral": "AI 降级，新闻中性",
            "ai_unavailable_news_positive": "AI 降级，新闻偏正面",
            "ai_unavailable_news_negative": "AI 降级，新闻偏负面",
            "ai_unavailable": "AI 降级",
            "market_data_degraded": "行情数据不足，保守评估",
        }
        return labels.get(value, value.replace("_", " "))

    def get_logs(self, limit: int = 20) -> list[AuditLog]:
        return self.audit_log_repository.list_logs(limit=limit)

    def _persist_order_risk_events(self, order: Order, events: list[RiskEvent]) -> list[RiskEvent]:
        if not order.status.startswith("rejected") or not events:
            return []

        order_events = [
            event.model_copy(update={"symbol": order.symbol, "correlation_id": order.correlation_id or order.order_id})
            for event in events
            if event.action in {"no_new_positions", "pause", "reduce_only"}
        ]
        if not order_events:
            return []

        persisted = self.risk_repository.append_events(order_events)
        for event in persisted:
            self.audit_log_repository.append_log(
                AuditLog(
                    level=Severity.WARNING,
                    module="risk",
                    symbol=order.symbol,
                    message=f"Risk event persisted: {event.rule} -> {event.action}: {event.reason}",
                    correlation_id=order.correlation_id or order.order_id,
                ),
            )
        return persisted

    @staticmethod
    def _build_order_signal(request: DryRunOrderRequest, correlation_id: str) -> StrategySignal:
        return StrategySignal(
            symbol=request.symbol,
            strategy=request.strategy or "manual",
            action=request.action,
            price=request.price or 0,
            reason=f"Dry-run order request received: {request.action.value} {request.quantity:g} {request.symbol}",
            correlation_id=correlation_id,
        )

    @staticmethod
    def _signal_blocker(order_status: str, risk_status: RiskStatus, ai: AiAnalysis) -> str | None:
        if order_status.startswith("rejected_by_risk"):
            return f"risk:{risk_status.value}"
        if order_status.startswith("rejected"):
            return "trading_validation"
        if ai.risk_level.value in {"high", "extreme"} or ai.allowed_direction.value == "none":
            return f"ai:{ai.risk_level.value}"
        return None

    def _risk_status_from_trace_events(self, correlation_id: str) -> RiskStatus | None:
        events = self.risk_repository.list_events_by_correlation_id(correlation_id, limit=100)
        actions = {event.action for event in events}
        if "no_new_positions" in actions:
            return RiskStatus.NO_NEW_POSITIONS
        if "pause" in actions:
            return RiskStatus.PAUSED
        if "reduce_only" in actions:
            return RiskStatus.REDUCE_ONLY
        if self.portfolio_repository.get_order_by_correlation_id(correlation_id) is not None:
            return RiskStatus.ALLOW_TRADING
        return None

    def _risk_market_context(self) -> MarketOverview:
        try:
            return self.get_market_overview(
                symbol=self.settings.default_symbol,
                timeframe=self.settings.default_timeframe,
                exchange=ExchangeId(self.settings.default_exchange),
                limit=50,
                prefer_live=False,
            )
        except (ImportError, ValueError, ExchangeMarketDataError):
            return self._empty_market_overview(
                symbol=self.settings.default_symbol,
                timeframe=self.settings.default_timeframe,
                exchange=ExchangeId.BINANCE,
                data_integrity="exchange_error:risk_context_unavailable",
            )

    def get_settings_summary(self) -> SettingsSummary:
        news_feeds = self._news_feed_sources()
        binance_private_api_configured = bool(
            self.settings.binance_api_key and self.settings.binance_api_secret,
        )
        okx_private_api_configured = bool(
            self.settings.okx_api_key
            and self.settings.okx_api_secret
            and self.settings.okx_api_passphrase,
        )
        return SettingsSummary(
            exchanges=[
                {
                    "id": "binance",
                    "public_market_data": str(self.settings.enable_public_exchange_data).lower(),
                    "api_key_configured": binance_private_api_configured,
                    "api_key_value_configured": bool(self.settings.binance_api_key),
                    "api_secret_configured": bool(self.settings.binance_api_secret),
                    "api_passphrase_configured": False,
                    "requires_passphrase": False,
                    "spot_trading_enabled": self.settings.binance_spot_trading_enabled,
                    "sandbox": self.settings.binance_sandbox,
                    "withdraw_permission": "disabled",
                },
                {
                    "id": "okx",
                    "public_market_data": str(self.settings.enable_public_exchange_data).lower(),
                    "api_key_configured": okx_private_api_configured,
                    "api_key_value_configured": bool(self.settings.okx_api_key),
                    "api_secret_configured": bool(self.settings.okx_api_secret),
                    "api_passphrase_configured": bool(self.settings.okx_api_passphrase),
                    "requires_passphrase": True,
                    "spot_trading_enabled": self.settings.okx_spot_trading_enabled,
                    "sandbox": self.settings.okx_sandbox,
                    "withdraw_permission": "disabled",
                },
            ],
            ai_proxies=[
                {
                    "id": self.settings.ai_proxy_a_provider,
                    "model": self.settings.ai_proxy_a_model,
                    "priority": self.settings.ai_proxy_a_priority,
                    "enabled": self._ai_proxy_is_enabled(
                        self.settings.ai_proxy_a_provider,
                        self.settings.ai_proxy_a_base_url,
                        self.settings.ai_proxy_a_api_key,
                        self.settings.ai_proxy_a_enabled,
                    ),
                    "base_url": self.settings.ai_proxy_a_base_url,
                    "api_format": self.settings.ai_proxy_a_api_format,
                    "api_key_configured": bool(self.settings.ai_proxy_a_api_key),
                    "requires_api_key": ai_provider_requires_api_key(self.settings.ai_proxy_a_provider),
                },
                {
                    "id": self.settings.ai_proxy_b_provider,
                    "model": self.settings.ai_proxy_b_model,
                    "priority": self.settings.ai_proxy_b_priority,
                    "enabled": self._ai_proxy_is_enabled(
                        self.settings.ai_proxy_b_provider,
                        self.settings.ai_proxy_b_base_url,
                        self.settings.ai_proxy_b_api_key,
                        self.settings.ai_proxy_b_enabled,
                    ),
                    "base_url": self.settings.ai_proxy_b_base_url or "",
                    "api_format": self.settings.ai_proxy_b_api_format,
                    "api_key_configured": bool(self.settings.ai_proxy_b_api_key),
                    "requires_api_key": ai_provider_requires_api_key(self.settings.ai_proxy_b_provider),
                },
                {
                    "id": self.settings.ai_proxy_c_provider,
                    "model": self.settings.ai_proxy_c_model,
                    "priority": self.settings.ai_proxy_c_priority,
                    "enabled": self._ai_proxy_is_enabled(
                        self.settings.ai_proxy_c_provider,
                        self.settings.ai_proxy_c_base_url,
                        self.settings.ai_proxy_c_api_key,
                        self.settings.ai_proxy_c_enabled,
                    ),
                    "base_url": self.settings.ai_proxy_c_base_url or "",
                    "api_format": self.settings.ai_proxy_c_api_format,
                    "api_key_configured": bool(self.settings.ai_proxy_c_api_key),
                    "requires_api_key": ai_provider_requires_api_key(self.settings.ai_proxy_c_provider),
                },
            ],
            ai_provider_templates=[
                {
                    "id": template.id,
                    "name": template.name,
                    "base_url": template.base_url,
                    "default_model": template.default_model,
                    "api_format": template.api_format,
                    "requires_api_key": template.requires_api_key,
                    "description": template.description,
                }
                for template in AI_PROVIDER_TEMPLATES
            ],
            data={
                "mysql_host": self.settings.mysql_host,
                "repository_backend": self.settings.repository_backend,
                "default_exchange": self.settings.default_exchange,
                "default_symbol": self.settings.default_symbol,
                "default_timeframe": self.settings.default_timeframe,
                "live_trading_enabled": str(self.settings.live_trading_enabled).lower(),
                "public_exchange_data": str(self.settings.enable_public_exchange_data).lower(),
                "news_sentiment": str(self.settings.enable_news_sentiment).lower(),
                "news_feed_count": len(news_feeds),
                "news_cache_ttl_seconds": self.settings.news_cache_ttl_seconds,
                "max_data_latency_seconds": self.settings.max_data_latency_seconds,
                "schedule_enabled": str(self.settings.schedule_enabled).lower(),
                "schedule_time": self.settings.schedule_time,
                "schedule_times": self.settings.schedule_times or self.settings.schedule_time,
                "schedule_run_immediately": str(self.settings.schedule_run_immediately).lower(),
            },
            news_feeds=news_feeds,
            notifications=self.notification_service.configured_channels(),
            safety_checks=[
                {"name": "Spot only", "status": "passed"},
                {"name": "Contract disabled", "status": "passed"},
                {"name": "Withdraw permission", "status": "must_be_disabled"},
                {
                    "name": "Exchange account binding",
                    "status": "passed" if binance_private_api_configured or okx_private_api_configured else "required",
                },
                {"name": "Live confirmation", "status": "required"},
                {"name": "Kill Switch", "status": "enabled"},
            ],
        )

    def update_ai_proxy_settings(self, request: AiProxySettingsUpdateRequest) -> SettingsSummary:
        env_updates: dict[str, str] = {}
        seen_slots: set[str] = set()
        for proxy in request.proxies:
            slot = proxy.slot.upper()
            if slot in seen_slots:
                raise ValueError(f"duplicate AI proxy slot: {slot}")
            seen_slots.add(slot)

            prefix = f"AI_PROXY_{slot}"
            env_updates.update(
                {
                    f"{prefix}_BASE_URL": proxy.base_url.strip(),
                    f"{prefix}_PROVIDER": proxy.provider.strip(),
                    f"{prefix}_MODEL": proxy.model.strip(),
                    f"{prefix}_PRIORITY": str(proxy.priority),
                    f"{prefix}_ENABLED": str(proxy.enabled).lower(),
                    f"{prefix}_API_FORMAT": proxy.api_format.strip(),
                },
            )
            if proxy.api_key is not None:
                env_updates[f"{prefix}_API_KEY"] = proxy.api_key.strip()

        env_file = self._write_env_updates(env_updates)
        self._reload_settings(env_file)
        return self.get_settings_summary()

    def test_ai_proxy_connection(
        self,
        request: AiProxyConnectionTestRequest,
    ) -> AiProxyConnectionTestResult:
        proxy = request.proxy
        provider = proxy.provider.strip()
        base_url = proxy.base_url.strip()
        model = proxy.model.strip()
        api_key = self._resolve_ai_proxy_api_key(proxy)

        if not provider:
            return self._ai_connection_test_result(
                provider=provider,
                model=model,
                success=False,
                message="服务商不能为空。",
            )
        if not base_url:
            return self._ai_connection_test_result(
                provider=provider,
                model=model,
                success=False,
                message="Base URL 不能为空。",
            )
        if not model:
            return self._ai_connection_test_result(
                provider=provider,
                model=model,
                success=False,
                message="模型 ID 不能为空。",
            )
        if ai_provider_requires_api_key(provider) and not api_key:
            return self._ai_connection_test_result(
                provider=provider,
                model=model,
                success=False,
                message="该服务商需要 API Key，请填写后再测试。",
            )

        started_at = time.perf_counter()
        used_saved_api_key = not bool(proxy.api_key and proxy.api_key.strip()) and bool(api_key)
        try:
            service = OpenAiCompatibleAiService(
                proxy=AiProxyConfig(
                    provider=provider,
                    base_url=base_url,
                    api_key=api_key,
                    model=model,
                    priority=proxy.priority,
                    api_format=proxy.api_format,
                ),
                timeout_seconds=request.timeout_seconds,
            )
            analysis = service.analyze_empty_context()
        except AiServiceUnavailable as exc:
            return self._ai_connection_test_result(
                provider=provider,
                model=model,
                success=False,
                message=self._public_ai_connection_error(exc),
                latency_ms=self._elapsed_ms(started_at),
                used_saved_api_key=used_saved_api_key,
            )

        return self._ai_connection_test_result(
            provider=analysis.provider,
            model=analysis.model,
            success=True,
            message="模型连通性正常，已返回有效结构化 JSON。",
            latency_ms=self._elapsed_ms(started_at),
            used_saved_api_key=used_saved_api_key,
        )

    def _resolve_ai_proxy_api_key(self, proxy) -> str | None:
        api_key = proxy.api_key.strip() if proxy.api_key is not None else ""
        if api_key:
            return api_key

        slot = proxy.slot.upper()
        saved_key_by_slot = {
            "A": self.settings.ai_proxy_a_api_key,
            "B": self.settings.ai_proxy_b_api_key,
            "C": self.settings.ai_proxy_c_api_key,
        }
        saved_provider_by_slot = {
            "A": self.settings.ai_proxy_a_provider,
            "B": self.settings.ai_proxy_b_provider,
            "C": self.settings.ai_proxy_c_provider,
        }
        if saved_provider_by_slot.get(slot) != proxy.provider:
            return None
        saved_key = saved_key_by_slot.get(slot)
        return saved_key.strip() if saved_key else None

    @staticmethod
    def _ai_connection_test_result(
        *,
        provider: str,
        model: str,
        success: bool,
        message: str,
        latency_ms: int = 0,
        used_saved_api_key: bool = False,
    ) -> AiProxyConnectionTestResult:
        return AiProxyConnectionTestResult(
            success=success,
            provider=provider,
            model=model,
            message=message,
            latency_ms=latency_ms,
            used_saved_api_key=used_saved_api_key,
        )

    @staticmethod
    def _elapsed_ms(started_at: float) -> int:
        return max(0, int((time.perf_counter() - started_at) * 1000))

    @staticmethod
    def _public_ai_connection_error(exc: Exception) -> str:
        text = str(exc).replace("\n", " ").strip()
        return text[:300] + ("..." if len(text) > 300 else "")

    def update_exchange_account_settings(
        self,
        request: ExchangeAccountSettingsUpdateRequest,
    ) -> SettingsSummary:
        env_updates: dict[str, str] = {}
        seen_exchanges: set[ExchangeId] = set()
        for account in request.accounts:
            if account.exchange in seen_exchanges:
                raise ValueError(f"duplicate exchange account: {account.exchange.value}")
            seen_exchanges.add(account.exchange)
            env_updates.update(self._exchange_account_env_updates(account))

        env_file = self._write_env_updates(env_updates)
        self._reload_settings(env_file)
        return self.get_settings_summary()

    def test_exchange_account_connection(
        self,
        request: ExchangeAccountConnectionTestRequest,
    ) -> ExchangeAccountConnectionTestResult:
        account = request.account
        api_key, api_secret, passphrase = self._resolve_exchange_account_credentials(account)
        missing_fields = self._missing_exchange_account_fields(account, api_key, api_secret, passphrase)
        if missing_fields:
            return self._exchange_account_connection_test_result(
                exchange=account.exchange,
                success=False,
                message=f"请先填写 {', '.join(missing_fields)} 后再测试。",
            )

        started_at = time.perf_counter()
        used_saved_credentials = self._exchange_account_test_used_saved_credentials(account)
        try:
            balance_asset_count = self._probe_exchange_account_connection(
                account=account,
                api_key=api_key,
                api_secret=api_secret,
                passphrase=passphrase,
                timeout_seconds=request.timeout_seconds,
            )
        except (ExchangeTradingError, ExchangeTradingNotConfiguredError, AttributeError) as exc:
            return self._exchange_account_connection_test_result(
                exchange=account.exchange,
                success=False,
                message=f"交易所账号连通性测试失败：{self._public_exchange_account_error(exc)}",
                latency_ms=self._elapsed_ms(started_at),
                used_saved_credentials=used_saved_credentials,
            )

        return self._exchange_account_connection_test_result(
            exchange=account.exchange,
            success=True,
            message="交易所账号连通性正常，已完成只读余额校验。",
            latency_ms=self._elapsed_ms(started_at),
            used_saved_credentials=used_saved_credentials,
            balance_asset_count=balance_asset_count,
        )

    def _resolve_exchange_account_credentials(
        self,
        account: ExchangeAccountSettingsUpdate,
    ) -> tuple[str, str, str | None]:
        api_key = account.api_key.strip() if account.api_key is not None else ""
        api_secret = account.api_secret.strip() if account.api_secret is not None else ""
        passphrase = account.passphrase.strip() if account.passphrase is not None else ""

        if account.exchange == ExchangeId.BINANCE:
            return (
                api_key or (self.settings.binance_api_key or "").strip(),
                api_secret or (self.settings.binance_api_secret or "").strip(),
                None,
            )

        if account.exchange == ExchangeId.OKX:
            return (
                api_key or (self.settings.okx_api_key or "").strip(),
                api_secret or (self.settings.okx_api_secret or "").strip(),
                passphrase or (self.settings.okx_api_passphrase or "").strip(),
            )

        return api_key, api_secret, passphrase or None

    @staticmethod
    def _missing_exchange_account_fields(
        account: ExchangeAccountSettingsUpdate,
        api_key: str,
        api_secret: str,
        passphrase: str | None,
    ) -> list[str]:
        missing = []
        if not api_key:
            missing.append("API Key")
        if not api_secret:
            missing.append("API Secret")
        if account.exchange == ExchangeId.OKX and not passphrase:
            missing.append("Passphrase")
        return missing

    def _exchange_account_test_used_saved_credentials(self, account: ExchangeAccountSettingsUpdate) -> bool:
        if account.exchange == ExchangeId.BINANCE:
            return (
                self._uses_saved_secret(account.api_key, self.settings.binance_api_key)
                or self._uses_saved_secret(account.api_secret, self.settings.binance_api_secret)
            )

        if account.exchange == ExchangeId.OKX:
            return (
                self._uses_saved_secret(account.api_key, self.settings.okx_api_key)
                or self._uses_saved_secret(account.api_secret, self.settings.okx_api_secret)
                or self._uses_saved_secret(account.passphrase, self.settings.okx_api_passphrase)
            )

        return False

    @staticmethod
    def _uses_saved_secret(candidate: str | None, saved_value: str | None) -> bool:
        return not (candidate is not None and candidate.strip()) and bool(saved_value)

    @staticmethod
    def _probe_exchange_account_connection(
        *,
        account: ExchangeAccountSettingsUpdate,
        api_key: str,
        api_secret: str,
        passphrase: str | None,
        timeout_seconds: int,
    ) -> int:
        if account.exchange == ExchangeId.BINANCE:
            return WorkbenchApplicationService._probe_binance_account_connection(
                api_key=api_key,
                api_secret=api_secret,
                timeout_seconds=timeout_seconds,
            )

        client = WorkbenchApplicationService._build_exchange_account_test_client(
            account=account,
            api_key=api_key,
            api_secret=api_secret,
            passphrase=passphrase,
            timeout_seconds=timeout_seconds,
        )
        return len(client.get_balances())

    @staticmethod
    def _probe_binance_account_connection(
        *,
        api_key: str,
        api_secret: str,
        timeout_seconds: int,
    ) -> int:
        timeout = httpx.Timeout(timeout_seconds, connect=min(timeout_seconds, 2))
        errors: list[str] = []
        for base_url in BinanceSpotMarketClient.candidate_base_urls("https://api.binance.com")[:5]:
            try:
                return WorkbenchApplicationService._request_binance_account_probe(
                    base_url=base_url,
                    api_key=api_key,
                    api_secret=api_secret,
                    timeout=timeout,
                )
            except (httpx.RequestError, ValueError, KeyError, TypeError) as exc:
                errors.append(f"{base_url}: {WorkbenchApplicationService._public_exchange_account_error(exc)}")
                continue

        raise ExchangeTradingError(
            "Binance API 网络不可达或响应超时，请检查本机网络、代理、DNS 或所在地区是否允许访问；"
            + " | ".join(errors[:2]),
        )

    @staticmethod
    def _request_binance_account_probe(
        *,
        base_url: str,
        api_key: str,
        api_secret: str,
        timeout: httpx.Timeout,
    ) -> int:
        timestamp = int(time.time() * 1000)
        query = f"timestamp={timestamp}&recvWindow=10000"
        signature = hmac.new(api_secret.encode(), query.encode(), hashlib.sha256).hexdigest()
        headers = {"X-MBX-APIKEY": api_key}
        with httpx.Client(base_url=base_url, timeout=timeout, headers=headers) as client:
            response = client.get("/api/v3/account", params=f"{query}&signature={signature}")

        if response.status_code >= 400:
            message = WorkbenchApplicationService._binance_error_message(response)
            raise ExchangeTradingError(f"Binance 账户签名校验失败：{message}")

        payload = response.json()
        balances = payload.get("balances")
        if not isinstance(balances, list):
            raise ExchangeTradingError("Binance 账户响应缺少 balances 字段")
        return len(
            [
                balance
                for balance in balances
                if WorkbenchApplicationService._positive_decimal_text(balance.get("free"))
                or WorkbenchApplicationService._positive_decimal_text(balance.get("locked"))
            ],
        )

    @staticmethod
    def _binance_error_message(response: httpx.Response) -> str:
        try:
            payload = response.json()
        except ValueError:
            return f"HTTP {response.status_code}"
        code = payload.get("code")
        message = payload.get("msg")
        if message:
            return f"HTTP {response.status_code}, code={code}, msg={message}"
        return f"HTTP {response.status_code}"

    @staticmethod
    def _positive_decimal_text(value: object) -> bool:
        try:
            return float(value or 0) > 0
        except (TypeError, ValueError):
            return False

    @staticmethod
    def _build_exchange_account_test_client(
        *,
        account: ExchangeAccountSettingsUpdate,
        api_key: str,
        api_secret: str,
        passphrase: str | None,
        timeout_seconds: int,
    ) -> CcxtSpotTradingClient:
        exchange_id_by_account = {
            ExchangeId.BINANCE: "binance",
            ExchangeId.OKX: "okx",
        }
        return CcxtSpotTradingClient(
            exchange=account.exchange,
            exchange_id=exchange_id_by_account[account.exchange],
            api_key=api_key,
            api_secret=api_secret,
            password=passphrase,
            sandbox=account.sandbox,
            timeout_seconds=timeout_seconds,
        )

    @staticmethod
    def _exchange_account_connection_test_result(
        *,
        exchange: ExchangeId,
        success: bool,
        message: str,
        latency_ms: int = 0,
        used_saved_credentials: bool = False,
        balance_asset_count: int = 0,
    ) -> ExchangeAccountConnectionTestResult:
        return ExchangeAccountConnectionTestResult(
            success=success,
            exchange=exchange,
            message=message,
            latency_ms=latency_ms,
            used_saved_credentials=used_saved_credentials,
            balance_asset_count=balance_asset_count,
        )

    @staticmethod
    def _public_exchange_account_error(exc: Exception) -> str:
        text = str(exc).replace("\n", " ").strip()
        cause = exc.__cause__
        if cause is not None and cause.__class__.__name__ not in text:
            text = f"{cause.__class__.__name__}: {text}"
        text = re.sub(r"\?[^ ]+", "?<redacted>", text)
        text = re.sub(r"(?i)(api[-_ ]?key|signature|timestamp|recvWindow)=([^&\\s]+)", r"\1=<redacted>", text)
        return text[:240] + ("..." if len(text) > 240 else "")

    def _exchange_account_env_updates(self, account: ExchangeAccountSettingsUpdate) -> dict[str, str]:
        if account.exchange == ExchangeId.BINANCE:
            api_key = self._next_secret_value(account.api_key, self.settings.binance_api_key)
            api_secret = self._next_secret_value(account.api_secret, self.settings.binance_api_secret)
            if account.spot_trading_enabled and (not api_key or not api_secret):
                raise ValueError("BINANCE_API_KEY and BINANCE_API_SECRET are required before enabling Binance spot trading")
            updates = {
                "BINANCE_SPOT_TRADING_ENABLED": str(account.spot_trading_enabled).lower(),
                "BINANCE_SANDBOX": str(account.sandbox).lower(),
            }
            if account.api_key is not None:
                updates["BINANCE_API_KEY"] = account.api_key.strip()
            if account.api_secret is not None:
                updates["BINANCE_API_SECRET"] = account.api_secret.strip()
            return updates

        if account.exchange == ExchangeId.OKX:
            api_key = self._next_secret_value(account.api_key, self.settings.okx_api_key)
            api_secret = self._next_secret_value(account.api_secret, self.settings.okx_api_secret)
            passphrase = self._next_secret_value(account.passphrase, self.settings.okx_api_passphrase)
            if account.spot_trading_enabled and (not api_key or not api_secret or not passphrase):
                raise ValueError(
                    "OKX_API_KEY, OKX_API_SECRET and OKX_API_PASSPHRASE are required before enabling OKX spot trading",
                )
            updates = {
                "OKX_SPOT_TRADING_ENABLED": str(account.spot_trading_enabled).lower(),
                "OKX_SANDBOX": str(account.sandbox).lower(),
            }
            if account.api_key is not None:
                updates["OKX_API_KEY"] = account.api_key.strip()
            if account.api_secret is not None:
                updates["OKX_API_SECRET"] = account.api_secret.strip()
            if account.passphrase is not None:
                updates["OKX_API_PASSPHRASE"] = account.passphrase.strip()
            return updates

        raise ValueError(f"unsupported exchange account: {account.exchange.value}")

    def update_notification_settings(
        self,
        request: NotificationSettingsUpdateRequest,
    ) -> SettingsSummary:
        env_updates: dict[str, str] = {}
        seen_providers: set[NotificationProvider] = set()
        for channel in request.channels:
            if channel.provider in seen_providers:
                raise ValueError(f"duplicate notification provider: {channel.provider.value}")
            seen_providers.add(channel.provider)
            env_updates.update(self._notification_channel_env_updates(channel))

        if not env_updates:
            return self.get_settings_summary()

        env_file = self._write_env_updates(env_updates)
        self._reload_settings(env_file)
        return self.get_settings_summary()

    def update_daily_push_settings(
        self,
        request: DailyPushSettingsUpdateRequest,
    ) -> SettingsSummary:
        schedule_times = request.schedule_times.strip()
        if schedule_times:
            invalid_items = [
                item.strip()
                for item in schedule_times.split(",")
                if item.strip() and not re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d", item.strip())
            ]
            if invalid_items:
                raise ValueError(f"invalid schedule time values: {', '.join(invalid_items)}")

        env_file = self._write_env_updates(
            {
                "SCHEDULE_ENABLED": str(request.enabled).lower(),
                "SCHEDULE_TIME": request.schedule_time.strip(),
                "SCHEDULE_TIMES": schedule_times,
                "SCHEDULE_RUN_IMMEDIATELY": str(request.run_immediately).lower(),
            },
        )
        self._reload_settings(env_file)
        return self.get_settings_summary()

    def _notification_channel_env_updates(
        self,
        channel: NotificationChannelSettingsUpdate,
    ) -> dict[str, str]:
        if channel.provider == NotificationProvider.FEISHU:
            return self._notification_webhook_env_update(
                "FEISHU_WEBHOOK_URL",
                channel.webhook_url,
            )

        if channel.provider == NotificationProvider.WECOM:
            return self._notification_webhook_env_update(
                "WECOM_WEBHOOK_URL",
                channel.webhook_url,
            )

        if channel.provider == NotificationProvider.SLACK:
            return self._notification_webhook_env_update(
                "SLACK_WEBHOOK_URL",
                channel.webhook_url,
            )

        if channel.provider == NotificationProvider.DISCORD:
            return self._notification_webhook_env_update(
                "DISCORD_WEBHOOK_URL",
                channel.webhook_url,
            )

        if channel.provider == NotificationProvider.TELEGRAM:
            updates: dict[str, str] = {}
            if channel.telegram_bot_token is not None:
                updates["TELEGRAM_BOT_TOKEN"] = channel.telegram_bot_token.strip()
            if channel.telegram_chat_id is not None:
                updates["TELEGRAM_CHAT_ID"] = channel.telegram_chat_id.strip()
            return updates

        if channel.provider == NotificationProvider.EMAIL:
            updates = {}
            if channel.email_smtp_host is not None:
                updates["EMAIL_SMTP_HOST"] = channel.email_smtp_host.strip()
            if channel.email_smtp_port is not None:
                updates["EMAIL_SMTP_PORT"] = str(channel.email_smtp_port)
            if channel.email_smtp_username is not None:
                updates["EMAIL_SMTP_USERNAME"] = channel.email_smtp_username.strip()
            if channel.email_smtp_password is not None:
                updates["EMAIL_SMTP_PASSWORD"] = channel.email_smtp_password.strip()
            if channel.email_from is not None:
                updates["EMAIL_FROM"] = channel.email_from.strip()
            if channel.email_to is not None:
                updates["EMAIL_TO"] = channel.email_to.strip()
            if channel.email_use_tls is not None:
                updates["EMAIL_USE_TLS"] = str(channel.email_use_tls).lower()
            return updates

        raise ValueError(f"unsupported notification provider: {channel.provider.value}")

    @staticmethod
    def _notification_webhook_env_update(key: str, webhook_url: str | None) -> dict[str, str]:
        if webhook_url is None:
            return {}
        return {key: webhook_url.strip()}

    @staticmethod
    def _next_secret_value(new_value: str | None, current_value: str | None) -> str:
        return new_value.strip() if new_value is not None else (current_value or "")

    def _news_feed_sources(self) -> list[NewsFeedSource]:
        return [
            self._news_feed_source(feed_url)
            for feed_url in self.settings.news_feed_urls.split(",")
            if feed_url.strip()
        ]

    @staticmethod
    def _news_feed_source(feed_url: str) -> NewsFeedSource:
        clean_feed_url = feed_url.strip()
        parsed = urlparse(clean_feed_url)
        raw_host = (parsed.netloc or parsed.path).split("/")[0]
        host = raw_host.removeprefix("www.")
        website_url = f"{parsed.scheme or 'https'}://{raw_host}" if raw_host else clean_feed_url
        known_names = {
            "coindesk.com": "CoinDesk",
            "cointelegraph.com": "Cointelegraph",
            "decrypt.co": "Decrypt",
            "theblock.co": "The Block",
            "blockworks.com": "Blockworks",
            "cryptoslate.com": "CryptoSlate",
            "beincrypto.com": "BeInCrypto",
            "newsbtc.com": "NewsBTC",
        }

        return NewsFeedSource(
            name=known_names.get(host, host or clean_feed_url),
            website_url=website_url.rstrip("/"),
            feed_url=clean_feed_url,
        )

    @staticmethod
    def _ai_proxy_is_enabled(
        provider: str,
        base_url: str | None,
        api_key: str | None,
        enabled: bool,
    ) -> bool:
        if not enabled or not base_url:
            return False
        return bool(api_key) or not ai_provider_requires_api_key(provider)

    @staticmethod
    def _write_env_updates(updates: dict[str, str]) -> Path:
        from app.core.config import ROOT_ENV_FILE

        env_file = Path(ROOT_ENV_FILE)
        existing_lines = env_file.read_text(encoding="utf-8").splitlines() if env_file.exists() else []
        pending = dict(updates)
        next_lines: list[str] = []

        for line in existing_lines:
            stripped = line.strip()
            if not stripped or stripped.startswith("#") or "=" not in line:
                next_lines.append(line)
                continue
            key = line.split("=", 1)[0].strip()
            if key not in pending:
                next_lines.append(line)
                continue
            next_lines.append(f"{key}={pending.pop(key)}")

        if pending:
            if next_lines and next_lines[-1] != "":
                next_lines.append("")
            for key in sorted(pending):
                next_lines.append(f"{key}={pending[key]}")

        env_file.write_text("\n".join(next_lines) + "\n", encoding="utf-8")
        return env_file

    def _current_public_market_status(self, probe: bool = True) -> tuple[list[ExchangeStatus], int | None]:
        exchanges = (ExchangeId.BINANCE, ExchangeId.OKX)
        if not self.settings.enable_public_exchange_data:
            return (
                [
                    ExchangeStatus(
                        exchange=exchange,
                        state=ConnectionState.OFFLINE,
                        message="public spot market data disabled",
                    )
                    for exchange in exchanges
                ],
                None,
            )

        cache_key = self._system_market_status_cache_key()
        cached = self._get_system_market_status_cache(cache_key)
        if cached is not None:
            return list(cached.exchanges), self._seconds_since(cached.data_checked_at)

        if not probe:
            return (
                [
                    ExchangeStatus(
                        exchange=exchange,
                        state=ConnectionState.DEGRADED,
                        message="public spot market data not probed",
                    )
                    for exchange in exchanges
                ],
                None,
            )

        statuses: list[ExchangeStatus] = []
        checked_at_values: list[datetime] = []
        for exchange in exchanges:
            status, data_checked_at = self._probe_public_exchange_status(exchange)
            statuses.append(status)
            if data_checked_at is not None:
                checked_at_values.append(data_checked_at)

        snapshot = SystemMarketStatusSnapshot(
            exchanges=tuple(statuses),
            data_checked_at=max(checked_at_values) if checked_at_values else None,
        )
        _SYSTEM_MARKET_STATUS_CACHE[cache_key] = TimedCacheEntry(
            value=snapshot,
            expires_at=time.monotonic() + max(1, self.settings.public_market_cache_ttl_seconds),
        )
        return statuses, self._seconds_since(snapshot.data_checked_at)

    def _system_market_status_cache_key(self) -> tuple[str, str, str, str]:
        return (
            self.settings.default_symbol,
            self.settings.default_timeframe,
            self.settings.binance_spot_base_url,
            self.settings.okx_rest_base_url,
        )

    @staticmethod
    def _get_system_market_status_cache(
        cache_key: tuple[str, str, str, str],
    ) -> SystemMarketStatusSnapshot | None:
        cached = _SYSTEM_MARKET_STATUS_CACHE.get(cache_key)
        if cached is None:
            return None
        if cached.expires_at <= time.monotonic():
            _SYSTEM_MARKET_STATUS_CACHE.pop(cache_key, None)
            return None
        return cached.value

    @staticmethod
    def _seconds_since(value: datetime | None) -> int | None:
        if value is None:
            return None
        return max(0, int((utc_now() - value).total_seconds()))

    def _probe_public_exchange_status(
        self,
        exchange: ExchangeId,
    ) -> tuple[ExchangeStatus, datetime | None]:
        started_at = time.monotonic()
        try:
            self._request_public_ticker_probe(exchange)
        except (ExchangeMarketDataError, httpx.HTTPError, ValueError, TypeError) as exc:
            return (
                ExchangeStatus(
                    exchange=exchange,
                    state=ConnectionState.OFFLINE,
                    latency_ms=None,
                    message=f"public spot market data check failed: {self._public_exception(exc)}",
                ),
                None,
            )

        checked_at = utc_now()
        latency_ms = max(1, int((time.monotonic() - started_at) * 1000))
        trade_status = (
            "private spot trading configured"
            if self._spot_trading_is_configured(exchange)
            else "private API not configured"
        )
        return (
            ExchangeStatus(
                exchange=exchange,
                state=ConnectionState.HEALTHY,
                latency_ms=latency_ms,
                last_checked_at=checked_at,
                message=(
                    "public spot market data checked; "
                    f"latency={latency_ms}ms; {trade_status}"
                ),
            ),
            checked_at,
        )

    def _request_public_ticker_probe(self, exchange: ExchangeId) -> None:
        timeout_seconds = min(max(self.settings.exchange_api_timeout_seconds, 0.5), 1.5)
        timeout = httpx.Timeout(timeout_seconds, connect=min(timeout_seconds, 0.75))
        symbol = self.settings.default_symbol
        if exchange == ExchangeId.BINANCE:
            errors: list[str] = []
            for base_url in BinanceSpotMarketClient.candidate_base_urls(
                self.settings.binance_spot_base_url,
            )[:2]:
                try:
                    with httpx.Client(base_url=base_url, timeout=timeout) as client:
                        response = client.get(
                            "/api/v3/ticker/price",
                            params={"symbol": BinanceSpotMarketClient.to_exchange_symbol(symbol)},
                        )
                    response.raise_for_status()
                    payload = response.json()
                    float(payload["price"])
                    return
                except (httpx.HTTPError, KeyError, TypeError, ValueError) as exc:
                    errors.append(f"{base_url}: {self._public_exception(exc)}")
            raise ExchangeMarketDataError("Binance ticker probe failed: " + " | ".join(errors))

        if exchange == ExchangeId.OKX:
            with httpx.Client(base_url=self.settings.okx_rest_base_url, timeout=timeout) as client:
                response = client.get(
                    "/api/v5/market/ticker",
                    params={"instId": OkxSpotMarketClient.to_exchange_symbol(symbol)},
                )
            response.raise_for_status()
            payload = response.json()
            if payload.get("code") != "0":
                raise ExchangeMarketDataError(f"OKX ticker probe response error: {payload}")
            data = payload.get("data")
            if not isinstance(data, list) or not data:
                raise ExchangeMarketDataError("OKX ticker probe response missing data")
            float(data[0]["last"])
            return

        raise ExchangeMarketDataError(f"Unsupported exchange: {exchange}")

    def _spot_trading_is_configured(self, exchange: ExchangeId) -> bool:
        if exchange == ExchangeId.BINANCE:
            return bool(
                self.settings.binance_spot_trading_enabled
                and self.settings.binance_api_key
                and self.settings.binance_api_secret
            )
        if exchange == ExchangeId.OKX:
            return bool(
                self.settings.okx_spot_trading_enabled
                and self.settings.okx_api_key
                and self.settings.okx_api_secret
                and self.settings.okx_api_passphrase
            )
        return False

    def _current_ai_proxy_status(self) -> AiProxyStatus:
        if isinstance(self.ai_service, AiRelayService):
            proxy = self.ai_service.current_proxy
            state = (
                ConnectionState.HEALTHY
                if self.ai_service.last_successful_proxy is not None
                else ConnectionState.DEGRADED
            )
            return AiProxyStatus(
                provider=proxy.provider,
                model=proxy.model,
                state=state,
                priority=proxy.priority,
                timeout_seconds=self.settings.ai_request_timeout_seconds,
                failover_ready=self.ai_service.failover_ready,
            )
        if isinstance(self.ai_service, RightCodeAiService):
            return AiProxyStatus(
                provider=self.ai_service.provider,
                model=self.ai_service.model,
                state=ConnectionState.DEGRADED,
                priority=self.ai_service.proxy.priority,
                timeout_seconds=self.settings.ai_request_timeout_seconds,
                failover_ready=self.settings.ai_proxy_b_enabled or self.settings.ai_proxy_c_enabled,
            )
        return AiProxyStatus(
            provider=self.ai_service.provider,
            model=self.ai_service.model,
            state=ConnectionState.DEGRADED,
            priority=1,
            timeout_seconds=self.settings.ai_request_timeout_seconds,
            failover_ready=False,
        )

    def _default_strategies(self) -> list[StrategyConfig]:
        return self.strategy_registry.list_default_configs()

    def _default_strategy(self, strategy_id: str) -> StrategyConfig | None:
        return self.strategy_registry.get_default_config(strategy_id)

    def _merge_strategy_definition(self, strategy: StrategyConfig) -> StrategyConfig:
        default = self._default_strategy(strategy.id)
        if default is None:
            return strategy.model_copy(
                update={
                    "description": strategy.description or "Strategy config is persisted but not registered in the strategy center.",
                    "supports_signals": False,
                    "supports_backtest": False,
                    "supports_live": False,
                },
            )
        return default.model_copy(
            update={
                "enabled": strategy.enabled,
                "mode": strategy.mode,
                "status": strategy.status,
                "parameters": strategy.parameters,
                "risk_controls": strategy.risk_controls,
                "recent_signals": strategy.recent_signals,
            },
            deep=True,
        )

    @staticmethod
    def _empty_backtest_result(
        request: BacktestRequest,
        status: str,
        message: str,
    ) -> BacktestResult:
        return BacktestResult(
            request=request,
            status=status,
            message=message,
            total_return_percent=0,
            annual_return_percent=0,
            max_drawdown_percent=0,
            win_rate_percent=0,
            profit_factor=0,
            trade_count=0,
            equity_curve=[],
            trades=[],
        )

    @staticmethod
    def _correlation_id(prefix: str) -> str:
        return f"{prefix}-{uuid4().hex[:12]}"

    def _assert_live_trading_ready(self, exchange: ExchangeId, allow_management: bool = False) -> None:
        if not self.settings.live_trading_enabled or self.settings.trading_mode != TradingMode.LIVE.value:
            raise ValueError("Live trading requires TRADING_MODE=live and LIVE_TRADING_ENABLED=true")
        if exchange == ExchangeId.BINANCE:
            if not self.settings.binance_spot_trading_enabled:
                raise ValueError("BINANCE_SPOT_TRADING_ENABLED must be true for Binance live trading")
            if not self.settings.binance_api_key or not self.settings.binance_api_secret:
                raise ValueError("BINANCE_API_KEY and BINANCE_API_SECRET are required")
            return
        if exchange == ExchangeId.OKX:
            if not self.settings.okx_spot_trading_enabled:
                raise ValueError("OKX_SPOT_TRADING_ENABLED must be true for OKX live trading")
            if not self.settings.okx_api_key or not self.settings.okx_api_secret or not self.settings.okx_api_passphrase:
                raise ValueError("OKX_API_KEY, OKX_API_SECRET and OKX_API_PASSPHRASE are required")
            return
        action = "management" if allow_management else "trading"
        raise ValueError(f"Unsupported exchange for live {action}: {exchange.value}")

    @staticmethod
    def _spot_order_side(action: SpotSignalAction) -> str:
        if action == SpotSignalAction.BUY:
            return "buy"
        if action == SpotSignalAction.SELL_EXISTING:
            return "sell"
        raise ValueError(f"Live spot order does not support action={action.value}")

    @staticmethod
    def _public_exception(exc: Exception) -> str:
        text = str(exc).replace("\n", " ").strip()
        return text[:240] + ("..." if len(text) > 240 else "")

    def _get_market_cache(self, cache_key: tuple[str, str, str, int, str]) -> MarketOverview | None:
        cached = _MARKET_OVERVIEW_CACHE.get(cache_key)
        if cached is None:
            return None
        if cached.expires_at <= time.monotonic():
            _MARKET_OVERVIEW_CACHE.pop(cache_key, None)
            return None
        return cached.value

    def _set_market_cache(self, cache_key: tuple[str, str, str, int, str], market: MarketOverview) -> None:
        _MARKET_OVERVIEW_CACHE[cache_key] = TimedCacheEntry(
            value=market,
            expires_at=time.monotonic() + max(1, self.settings.public_market_cache_ttl_seconds),
        )

    @staticmethod
    def _is_failure_cooling_down(failure_key: tuple[str, ...]) -> bool:
        expires_at = _EXTERNAL_FAILURE_COOLDOWNS.get(failure_key)
        if expires_at is None:
            return False
        if expires_at <= time.monotonic():
            _EXTERNAL_FAILURE_COOLDOWNS.pop(failure_key, None)
            return False
        return True

    def _set_failure_cooldown(self, failure_key: tuple[str, ...]) -> None:
        _EXTERNAL_FAILURE_COOLDOWNS[failure_key] = (
            time.monotonic() + max(1, self.settings.external_failure_cooldown_seconds)
        )

    def _get_public_exchange_market_overview(
        self,
        symbol: str | None,
        timeframe: str | None,
        exchange: ExchangeId | None,
        limit: int,
    ) -> MarketOverview:
        resolved_symbol = symbol or self.settings.default_symbol
        resolved_timeframe = timeframe or self.settings.default_timeframe
        resolved_exchange = exchange or ExchangeId(self.settings.default_exchange)
        client = get_spot_market_client(resolved_exchange, self.settings)
        snapshot = client.get_market_data(
            symbol=resolved_symbol,
            timeframe=resolved_timeframe,
            limit=limit,
        )
        self._cache_public_market_candles(
            exchange=resolved_exchange,
            symbol=resolved_symbol,
            timeframe=resolved_timeframe,
            candles=snapshot.candles,
        )
        closes = [candle.close for candle in snapshot.candles]

        return MarketOverview(
            symbol=resolved_symbol,
            timeframe=resolved_timeframe,
            exchange=resolved_exchange,
            last_price=snapshot.ticker.last_price,
            change_24h_percent=snapshot.ticker.change_24h_percent,
            volume_24h=snapshot.ticker.volume_24h,
            volatility=self._calculate_volatility(closes),
            rsi=self._calculate_rsi(closes),
            data_latency_seconds=max(0, int((utc_now() - snapshot.ticker.received_at).total_seconds())),
            data_integrity="live_public",
            candles=snapshot.candles,
        )

    def _cache_public_market_candles(
        self,
        exchange: ExchangeId,
        symbol: str,
        timeframe: str,
        candles: list[Candle],
    ) -> CandleCacheWriteResult:
        if self.settings.repository_backend != "mysql" or not candles:
            return CandleCacheWriteResult()

        from sqlalchemy import select

        from app.infrastructure.persistence.models import MarketCandleRecord
        from app.infrastructure.persistence.session import create_mysql_session_factory

        session_factory = create_mysql_session_factory(self.settings)
        session = session_factory()
        batch_size = 1000
        inserted = 0
        updated = 0
        try:
            for index in range(0, len(candles), batch_size):
                batch = candles[index : index + batch_size]
                timestamps = [_to_db_timestamp(candle.timestamp) for candle in batch]
                existing_records = {
                    _to_db_timestamp(record.timestamp): record
                    for record in session.scalars(
                        select(MarketCandleRecord).where(
                            MarketCandleRecord.exchange == exchange.value,
                            MarketCandleRecord.symbol == symbol,
                            MarketCandleRecord.timeframe == timeframe,
                            MarketCandleRecord.timestamp.in_(timestamps),
                        ),
                    ).all()
                }

                new_records: list[MarketCandleRecord] = []
                for candle in batch:
                    timestamp = _to_db_timestamp(candle.timestamp)
                    existing = existing_records.get(timestamp)
                    if existing is None:
                        new_records.append(
                            MarketCandleRecord(
                                exchange=exchange.value,
                                symbol=symbol,
                                timeframe=timeframe,
                                timestamp=timestamp,
                                open=candle.open,
                                high=candle.high,
                                low=candle.low,
                                close=candle.close,
                                volume=candle.volume,
                            ),
                        )
                        continue

                    if (
                        existing.open != candle.open
                        or existing.high != candle.high
                        or existing.low != candle.low
                        or existing.close != candle.close
                        or existing.volume != candle.volume
                    ):
                        existing.open = candle.open
                        existing.high = candle.high
                        existing.low = candle.low
                        existing.close = candle.close
                        existing.volume = candle.volume
                        updated += 1

                session.add_all(new_records)
                session.commit()
                inserted += len(new_records)
            return CandleCacheWriteResult(inserted=inserted, updated=updated)
        except Exception:
            session.rollback()
            return CandleCacheWriteResult()
        finally:
            session.close()

    def _get_local_market_candles(
        self,
        symbol: str,
        timeframe: str,
        exchange: ExchangeId,
        start_at: datetime,
        end_at: datetime,
    ) -> list[Candle]:
        if self.settings.repository_backend != "mysql":
            return []

        from sqlalchemy import select

        from app.infrastructure.persistence.models import MarketCandleRecord
        from app.infrastructure.persistence.session import create_mysql_session_factory

        session_factory = create_mysql_session_factory(self.settings)
        session = session_factory()
        try:
            records = list(
                session.scalars(
                    select(MarketCandleRecord)
                    .where(
                        MarketCandleRecord.exchange == exchange.value,
                        MarketCandleRecord.symbol == symbol,
                        MarketCandleRecord.timeframe == timeframe,
                        MarketCandleRecord.timestamp >= _to_db_timestamp(start_at),
                        MarketCandleRecord.timestamp <= _to_db_timestamp(end_at),
                    )
                    .order_by(MarketCandleRecord.timestamp),
                ).all(),
            )
        finally:
            session.close()

        candles = [
            Candle(
                timestamp=_from_db_timestamp(record.timestamp),
                open=record.open,
                high=record.high,
                low=record.low,
                close=record.close,
                volume=record.volume,
            )
            for record in records
        ]
        deduped = {candle.timestamp: candle for candle in candles}
        return sorted(deduped.values(), key=lambda candle: candle.timestamp)

    def _get_local_market_overview(
        self,
        symbol: str | None,
        timeframe: str | None,
        exchange: ExchangeId | None,
        limit: int,
        before: datetime | None = None,
        allow_stale: bool = False,
    ) -> MarketOverview | None:
        if self.settings.repository_backend != "mysql":
            return None

        from sqlalchemy import desc, select

        from app.infrastructure.persistence.models import MarketCandleRecord
        from app.infrastructure.persistence.session import create_mysql_session_factory

        resolved_symbol = symbol or self.settings.default_symbol
        resolved_timeframe = timeframe or self.settings.default_timeframe
        resolved_exchange = exchange or ExchangeId(self.settings.default_exchange)
        resolved_limit = max(50, min(limit, 1000))
        session_factory = create_mysql_session_factory(self.settings)
        session = session_factory()
        try:
            query = select(MarketCandleRecord).where(
                MarketCandleRecord.exchange == resolved_exchange.value,
                MarketCandleRecord.symbol == resolved_symbol,
                MarketCandleRecord.timeframe == resolved_timeframe,
            )
            if before is not None:
                query = query.where(MarketCandleRecord.timestamp < _to_db_timestamp(before))

            page_size = max(resolved_limit, min(resolved_limit * 3, 1000))
            offset = 0
            candles_by_timestamp: dict[datetime, Candle] = {}
            while len(candles_by_timestamp) < resolved_limit:
                records = list(
                    session.scalars(
                        query.order_by(
                            desc(MarketCandleRecord.timestamp),
                            desc(MarketCandleRecord.id),
                        )
                        .offset(offset)
                        .limit(page_size),
                    ).all(),
                )
                if not records:
                    break

                offset += len(records)
                for record in records:
                    timestamp = _from_db_timestamp(record.timestamp)
                    candles_by_timestamp.setdefault(
                        timestamp,
                        Candle(
                            timestamp=timestamp,
                            open=record.open,
                            high=record.high,
                            low=record.low,
                            close=record.close,
                            volume=record.volume,
                        ),
                    )

                if len(records) < page_size:
                    break
        finally:
            session.close()

        if not candles_by_timestamp:
            return None

        candles = sorted(candles_by_timestamp.values(), key=lambda candle: candle.timestamp)[-resolved_limit:]
        last_candle = candles[-1]
        data_latency_seconds = max(0, int((utc_now() - last_candle.timestamp).total_seconds()))
        if not allow_stale and self._is_market_cache_stale(resolved_timeframe, data_latency_seconds):
            return None
        return self._market_overview_from_candles(
            symbol=resolved_symbol,
            timeframe=resolved_timeframe,
            exchange=resolved_exchange,
            data_latency_seconds=data_latency_seconds,
            data_integrity="local_cache",
            candles=candles,
        )

    def _get_historical_market_overview(
        self,
        symbol: str,
        timeframe: str,
        exchange: ExchangeId,
        limit: int,
        before: datetime,
    ) -> MarketOverview | None:
        if not self.settings.enable_public_exchange_data:
            return None

        end_at = before.astimezone(timezone.utc) - timedelta(milliseconds=1)
        start_at = end_at - timedelta(seconds=self._timeframe_seconds(timeframe) * max(50, min(limit, 1000)) * 2)
        try:
            candles = self._fetch_historical_candles(
                exchange=exchange,
                symbol=symbol,
                timeframe=timeframe,
                start_at=start_at,
                end_at=end_at,
            )[-max(50, min(limit, 1000)):]
        except ExchangeMarketDataError:
            return None

        if not candles:
            return None

        self._cache_public_market_candles(
            exchange=exchange,
            symbol=symbol,
            timeframe=timeframe,
            candles=candles,
        )
        last_candle = candles[-1]
        return self._market_overview_from_candles(
            symbol=symbol,
            timeframe=timeframe,
            exchange=exchange,
            data_latency_seconds=max(0, int((utc_now() - last_candle.timestamp).total_seconds())),
            data_integrity="historical_public",
            candles=candles,
        )

    def _market_overview_from_candles(
        self,
        symbol: str,
        timeframe: str,
        exchange: ExchangeId,
        data_latency_seconds: int,
        data_integrity: str,
        candles: list[Candle],
    ) -> MarketOverview:
        closes = [candle.close for candle in candles]
        last_candle = candles[-1]
        periods_per_day = self._periods_per_day(timeframe)
        previous_day_index = max(0, len(candles) - periods_per_day - 1)
        previous_price = candles[previous_day_index].close
        change_24h_percent = (
            ((last_candle.close - previous_price) / previous_price) * 100
            if previous_price > 0
            else 0
        )
        volume_24h = sum(candle.volume for candle in candles[-periods_per_day:])

        return MarketOverview(
            symbol=symbol,
            timeframe=timeframe,
            exchange=exchange,
            last_price=last_candle.close,
            change_24h_percent=round(change_24h_percent, 2),
            volume_24h=volume_24h,
            volatility=self._calculate_volatility(closes),
            rsi=self._calculate_rsi(closes),
            data_latency_seconds=data_latency_seconds,
            data_integrity=data_integrity,
            candles=candles,
        )

    def _empty_market_overview(
        self,
        symbol: str | None,
        timeframe: str | None,
        exchange: ExchangeId | None,
        data_integrity: str = "empty",
    ) -> MarketOverview:
        return MarketOverview(
            symbol=symbol or self.settings.default_symbol,
            timeframe=timeframe or self.settings.default_timeframe,
            exchange=exchange or ExchangeId(self.settings.default_exchange),
            last_price=0,
            change_24h_percent=0,
            volume_24h=0,
            volatility=0,
            rsi=0,
            data_latency_seconds=0,
            data_integrity=data_integrity,
            candles=[],
        )

    @staticmethod
    def _calculate_rsi(closes: list[float], period: int = 14) -> float:
        if len(closes) <= period:
            return 0

        gains: list[float] = []
        losses: list[float] = []
        for previous, current in zip(closes[-period - 1 : -1], closes[-period:]):
            delta = current - previous
            gains.append(max(delta, 0))
            losses.append(abs(min(delta, 0)))

        average_gain = sum(gains) / period
        average_loss = sum(losses) / period
        if average_loss == 0:
            return 100
        relative_strength = average_gain / average_loss
        return round(100 - (100 / (1 + relative_strength)), 2)

    @staticmethod
    def _calculate_volatility(closes: list[float]) -> float:
        if len(closes) < 3:
            return 0

        returns = [
            math.log(current / previous)
            for previous, current in zip(closes[:-1], closes[1:])
            if previous > 0 and current > 0
        ]
        if len(returns) < 2:
            return 0
        mean_return = sum(returns) / len(returns)
        variance = sum((item - mean_return) ** 2 for item in returns) / (len(returns) - 1)
        return round(math.sqrt(variance), 6)

    @staticmethod
    def _periods_per_day(timeframe: str) -> int:
        return {
            "1m": 1440,
            "5m": 288,
            "15m": 96,
            "1h": 24,
            "4h": 6,
            "1d": 1,
        }.get(timeframe, 24)

    def _fetch_binance_historical_candles(
        self,
        symbol: str,
        timeframe: str,
        start_at: datetime,
        end_at: datetime,
    ) -> list[Candle]:
        exchange_symbol = BinanceSpotMarketClient.to_exchange_symbol(symbol)
        interval = BinanceSpotMarketClient.to_exchange_interval(timeframe)
        interval_ms = self._timeframe_seconds(timeframe) * 1000
        start_ms = int(start_at.timestamp() * 1000)
        end_ms = int(end_at.timestamp() * 1000)
        candles: list[Candle] = []

        with httpx.Client(
            base_url=self.settings.binance_spot_base_url.rstrip("/"),
            timeout=self.settings.exchange_api_timeout_seconds,
        ) as client:
            while start_ms <= end_ms:
                page_end_ms = min(end_ms, start_ms + (interval_ms * 999))
                response: httpx.Response | None = None
                for attempt in range(3):
                    try:
                        response = client.get(
                            "/api/v3/klines",
                            params={
                                "symbol": exchange_symbol,
                                "interval": interval,
                                "startTime": start_ms,
                                "endTime": page_end_ms,
                                "limit": 1000,
                            },
                        )
                        response.raise_for_status()
                        break
                    except httpx.RequestError as exc:
                        if attempt < 2:
                            time.sleep(0.5 * (attempt + 1))
                            continue
                        raise ExchangeMarketDataError(
                            f"Binance historical klines request failed at startTime={start_ms}: {exc}",
                        ) from exc
                    except httpx.HTTPStatusError as exc:
                        status_code = exc.response.status_code
                        response_text = exc.response.text[:300]
                        if attempt < 2 and status_code in {408, 418, 425, 429, 500, 502, 503, 504}:
                            time.sleep(0.5 * (attempt + 1))
                            continue
                        raise ExchangeMarketDataError(
                            "Binance historical klines request failed "
                            f"at startTime={start_ms}: HTTP {status_code} {response_text}",
                        ) from exc

                if response is None:
                    break

                payload = response.json()
                if not isinstance(payload, list) or not payload:
                    break

                page_candles = [
                    Candle(
                        timestamp=datetime.fromtimestamp(row[0] / 1000, tz=timezone.utc),
                        open=float(row[1]),
                        high=float(row[2]),
                        low=float(row[3]),
                        close=float(row[4]),
                        volume=float(row[5]),
                    )
                    for row in payload
                    if isinstance(row, list) and len(row) >= 6
                ]
                if not page_candles:
                    break

                candles.extend(page_candles)
                next_start_ms = int(page_candles[-1].timestamp.timestamp() * 1000) + interval_ms
                if next_start_ms <= start_ms:
                    break
                start_ms = next_start_ms

                if len(payload) < 1000:
                    break

        deduped = {candle.timestamp: candle for candle in candles}
        return [
            candle
            for candle in sorted(deduped.values(), key=lambda item: item.timestamp)
            if start_at <= candle.timestamp <= end_at
        ]

    def _fetch_historical_candles(
        self,
        exchange: ExchangeId,
        symbol: str,
        timeframe: str,
        start_at: datetime,
        end_at: datetime,
    ) -> list[Candle]:
        if exchange == ExchangeId.BINANCE:
            return self._fetch_binance_historical_candles(symbol, timeframe, start_at, end_at)
        if exchange == ExchangeId.OKX:
            return self._fetch_okx_historical_candles(symbol, timeframe, start_at, end_at)
        raise ExchangeMarketDataError(f"Unsupported exchange: {exchange.value}")

    def _fetch_okx_historical_candles(
        self,
        symbol: str,
        timeframe: str,
        start_at: datetime,
        end_at: datetime,
    ) -> list[Candle]:
        exchange_symbol = OkxSpotMarketClient.to_exchange_symbol(symbol)
        interval = OkxSpotMarketClient.to_exchange_interval(timeframe)
        start_ms = int(start_at.timestamp() * 1000)
        end_ms = int(end_at.timestamp() * 1000)
        cursor_ms = end_ms
        candles: list[Candle] = []

        with httpx.Client(
            base_url=self.settings.okx_rest_base_url.rstrip("/"),
            timeout=self.settings.exchange_api_timeout_seconds,
        ) as client:
            while cursor_ms >= start_ms:
                response: httpx.Response | None = None
                for attempt in range(3):
                    try:
                        response = client.get(
                            "/api/v5/market/history-candles",
                            params={
                                "instId": exchange_symbol,
                                "bar": interval,
                                "after": cursor_ms,
                                "limit": OKX_HISTORY_CANDLE_LIMIT,
                            },
                        )
                        response.raise_for_status()
                        break
                    except httpx.RequestError as exc:
                        if attempt < 2:
                            time.sleep(0.5 * (attempt + 1))
                            continue
                        raise ExchangeMarketDataError(
                            f"OKX historical candles request failed at after={cursor_ms}: {exc}",
                        ) from exc
                    except httpx.HTTPStatusError as exc:
                        status_code = exc.response.status_code
                        response_text = exc.response.text[:300]
                        if attempt < 2 and status_code in {408, 429, 500, 502, 503, 504}:
                            time.sleep(0.5 * (attempt + 1))
                            continue
                        raise ExchangeMarketDataError(
                            "OKX historical candles request failed "
                            f"at after={cursor_ms}: HTTP {status_code} {response_text}",
                        ) from exc

                if response is None:
                    break

                payload = response.json()
                page_rows = OkxSpotMarketClient._extract_data(payload, "historical candles")
                if not page_rows:
                    break

                page_candles = [
                    OkxSpotMarketClient._parse_candle(row, symbol=symbol)
                    for row in page_rows
                ]
                page_candles = [
                    candle
                    for candle in page_candles
                    if start_at <= candle.timestamp <= end_at
                ]
                candles.extend(page_candles)

                oldest_timestamp = min(
                    OkxSpotMarketClient._parse_candle(row, symbol=symbol).timestamp
                    for row in page_rows
                )
                next_cursor_ms = int(oldest_timestamp.timestamp() * 1000) - 1
                if next_cursor_ms >= cursor_ms:
                    break
                cursor_ms = next_cursor_ms

                if len(page_rows) < OKX_HISTORY_CANDLE_LIMIT:
                    break

        deduped = {candle.timestamp: candle for candle in candles}
        return sorted(deduped.values(), key=lambda item: item.timestamp)

    @staticmethod
    def _parse_date_boundary(value: str, end_of_day: bool = False) -> datetime:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        else:
            parsed = parsed.astimezone(timezone.utc)
        if end_of_day and "T" not in value:
            parsed = parsed + timedelta(days=1) - timedelta(milliseconds=1)
        return parsed

    @classmethod
    def _is_market_cache_stale(cls, timeframe: str, data_latency_seconds: int) -> bool:
        return data_latency_seconds > cls._timeframe_seconds(timeframe)

    @staticmethod
    def _timeframe_seconds(timeframe: str) -> int:
        return int(
            {
                "1m": timedelta(minutes=1),
                "5m": timedelta(minutes=5),
                "15m": timedelta(minutes=15),
                "1h": timedelta(hours=1),
                "4h": timedelta(hours=4),
                "1d": timedelta(days=1),
            }
            .get(timeframe, timedelta(hours=1))
            .total_seconds(),
        )

    @classmethod
    def _expected_candle_count(
        cls,
        timeframe: str,
        start_at: datetime,
        end_at: datetime,
    ) -> int:
        return int((end_at - start_at).total_seconds() // cls._timeframe_seconds(timeframe)) + 1
