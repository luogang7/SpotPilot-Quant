import time
from datetime import datetime, timedelta, timezone

import httpx
import pytest

from app.application.ai import AiServiceUnavailable
from app.application.news import CryptoNewsService
from app.application import workbench as workbench_module
from app.application.workbench import WorkbenchApplicationService, _SYSTEM_MARKET_STATUS_CACHE
from app.core.config import Settings
from app.domain.models import (
    AiAnalysis,
    ExchangeAccountConnectionTestRequest,
    AiProxyConnectionTestRequest,
    AiProxySettingsUpdate,
    AiProxySettingsUpdateRequest,
    AllowedDirection,
    BacktestRequest,
    Balance,
    Candle,
    ConnectionState,
    DailyPushSettingsUpdateRequest,
    DryRunOrderRequest,
    ExchangeAccountSettingsUpdate,
    ExchangeAccountSettingsUpdateRequest,
    ExchangeStatus,
    ExchangeId,
    HistoricalDataSyncRequest,
    LiveCancelOrderRequest,
    LiveOrderRequest,
    ManualClosePositionRequest,
    MarketOverview,
    NotificationChannelSettingsUpdate,
    NotificationProvider,
    NotificationSettingsUpdateRequest,
    NotificationTestRequest,
    Order,
    Position,
    RiskLevel,
    SpotSignalAction,
    StrategyUpdateRequest,
    utc_now,
)
from app.infrastructure.exchanges.base import ExchangeTradingError, MarketDataSnapshot, MarketTicker
from app.infrastructure.persistence.models import MarketCandleRecord
from app.infrastructure.repositories.memory import (
    EmptyAiAnalysisRepository,
    EmptyAuditLogRepository,
    EmptyPortfolioRepository,
    EmptyRiskRepository,
    EmptyStrategyRepository,
    EmptySystemStateRepository,
)


@pytest.fixture(autouse=True)
def clear_workbench_caches():
    workbench_module._MARKET_OVERVIEW_CACHE.clear()
    workbench_module._EXTERNAL_FAILURE_COOLDOWNS.clear()
    workbench_module._AI_ANALYSIS_CACHE.clear()
    workbench_module._NEWS_SENTIMENT_CACHE.clear()
    workbench_module._PORTFOLIO_SNAPSHOT_CACHE.clear()
    _SYSTEM_MARKET_STATUS_CACHE.clear()
    yield
    workbench_module._MARKET_OVERVIEW_CACHE.clear()
    workbench_module._EXTERNAL_FAILURE_COOLDOWNS.clear()
    workbench_module._AI_ANALYSIS_CACHE.clear()
    workbench_module._NEWS_SENTIMENT_CACHE.clear()
    workbench_module._PORTFOLIO_SNAPSHOT_CACHE.clear()
    _SYSTEM_MARKET_STATUS_CACHE.clear()


def make_service() -> WorkbenchApplicationService:
    return WorkbenchApplicationService(
        settings=Settings(
            _env_file=None,
            ENABLE_PUBLIC_EXCHANGE_DATA=False,
            REPOSITORY_BACKEND="memory",
        ),
        portfolio_repository=EmptyPortfolioRepository(),
        strategy_repository=EmptyStrategyRepository(),
        audit_log_repository=EmptyAuditLogRepository(),
        risk_repository=EmptyRiskRepository(),
        ai_analysis_repository=EmptyAiAnalysisRepository(),
        system_state_repository=EmptySystemStateRepository(),
    )


def make_candles(closes: list[float]) -> list[Candle]:
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    return [
        Candle(
            timestamp=start + timedelta(hours=index),
            open=close,
            high=close * 1.01,
            low=close * 0.99,
            close=close,
            volume=1000 + index,
        )
        for index, close in enumerate(closes)
    ]


class LowRiskAiService:
    provider = "test"
    model = "schema"

    def analyze_empty_context(self, *args: object, **kwargs: object) -> AiAnalysis:
        return AiAnalysis(
            market_regime="trend",
            sentiment_score=0,
            risk_level=RiskLevel.LOW,
            event_risk=False,
            allowed_direction=AllowedDirection.LONG_ONLY,
            confidence=0.8,
            provider=self.provider,
            model=self.model,
            rationale=[],
            structured_payload={},
        )


class FundedPortfolioRepository(EmptyPortfolioRepository):
    def list_balances(self) -> list[Balance]:
        return [Balance(asset="USDT", free=1000, locked=0, total=1000)]

    def list_positions(self) -> list[Position]:
        return [
            Position(
                symbol="BTC/USDT",
                quantity=0.001,
                average_price=50_000,
                current_price=51_000,
                unrealized_pnl=1,
            ),
        ]


def make_live_service() -> WorkbenchApplicationService:
    service = WorkbenchApplicationService(
        settings=Settings(
            _env_file=None,
            ENABLE_PUBLIC_EXCHANGE_DATA=False,
            REPOSITORY_BACKEND="memory",
            TRADING_MODE="live",
            LIVE_TRADING_ENABLED=True,
            BINANCE_API_KEY="key",
            BINANCE_API_SECRET="secret",
            BINANCE_SPOT_TRADING_ENABLED=True,
        ),
        portfolio_repository=FundedPortfolioRepository(),
        strategy_repository=EmptyStrategyRepository(),
        audit_log_repository=EmptyAuditLogRepository(),
        risk_repository=EmptyRiskRepository(),
        ai_analysis_repository=EmptyAiAnalysisRepository(),
        system_state_repository=EmptySystemStateRepository(),
    )
    service.ai_service = LowRiskAiService()
    service.get_ai_analysis = service.ai_service.analyze_empty_context
    service._risk_market_context = lambda: MarketOverview(
        symbol="BTC/USDT",
        timeframe="1h",
        exchange=ExchangeId.BINANCE,
        last_price=51_000,
        change_24h_percent=1,
        volume_24h=1000,
        volatility=1,
        rsi=50,
        data_latency_seconds=0,
        data_integrity="live_public",
        candles=[],
    )
    return service


def test_default_service_does_not_fabricate_account_data() -> None:
    service = make_service()
    dashboard = service.get_dashboard()
    trading = service.get_trading_summary()

    assert dashboard.positions == []
    assert dashboard.equity_curve == []
    assert dashboard.latest_signals == []
    assert trading.balances == []
    assert trading.positions == []
    assert trading.open_orders == []
    assert trading.historical_orders == []


def test_dashboard_fetches_live_balances_when_exchange_key_configured_in_dry_run(monkeypatch) -> None:
    calls: list[ExchangeId] = []

    class StubTradingClient:
        def get_balances(self) -> list[Balance]:
            return [
                Balance(asset="BTC", free=0.01, locked=0, total=0.01),
                Balance(asset="USDT", free=100, locked=0, total=100),
            ]

        def get_open_orders(self) -> list[Order]:
            raise AssertionError("dashboard should not fetch open orders")

    def stub_client(exchange, settings):
        calls.append(exchange)
        assert settings.live_trading_enabled is False
        return StubTradingClient()

    monkeypatch.setattr("app.application.workbench.get_spot_trading_client", stub_client)

    service = WorkbenchApplicationService(
        settings=Settings(
            _env_file=None,
            ENABLE_PUBLIC_EXCHANGE_DATA=False,
            REPOSITORY_BACKEND="memory",
            TRADING_MODE="dry_run",
            LIVE_TRADING_ENABLED=False,
            BINANCE_API_KEY="key",
            BINANCE_API_SECRET="secret",
            BINANCE_SPOT_TRADING_ENABLED=True,
        ),
        portfolio_repository=FundedPortfolioRepository(),
        strategy_repository=EmptyStrategyRepository(),
        audit_log_repository=EmptyAuditLogRepository(),
        risk_repository=EmptyRiskRepository(),
        ai_analysis_repository=EmptyAiAnalysisRepository(),
        system_state_repository=EmptySystemStateRepository(),
    )
    service._safe_spot_price = lambda exchange, symbol: 50_000 if symbol == "BTC/USDT" else None
    service._risk_market_context = lambda: MarketOverview(
        symbol="BTC/USDT",
        timeframe="1h",
        exchange=ExchangeId.BINANCE,
        last_price=50_000,
        change_24h_percent=1,
        volume_24h=1000,
        volatility=1,
        rsi=50,
        data_latency_seconds=0,
        data_integrity="live_public",
        candles=[],
    )

    dashboard = service.get_dashboard()

    equity_metric = next(metric for metric in dashboard.metrics if metric.label == "资产净值")
    assert calls == [ExchangeId.BINANCE]
    assert equity_metric.value == "$600.00"
    assert equity_metric.detail == "from live account snapshot"
    assert [position.symbol for position in dashboard.positions] == ["BTC/USDT"]


def test_dashboard_falls_back_when_live_balance_request_times_out(monkeypatch) -> None:
    calls: list[ExchangeId] = []
    audit_repository = EmptyAuditLogRepository()

    class SlowTradingClient:
        def get_balances(self) -> list[Balance]:
            calls.append(ExchangeId.BINANCE)
            time.sleep(0.2)
            return [Balance(asset="USDT", free=100, locked=0, total=100)]

        def get_open_orders(self) -> list[Order]:
            return []

    monkeypatch.setattr(
        "app.application.workbench.get_spot_trading_client",
        lambda exchange, settings: SlowTradingClient(),
    )

    service = WorkbenchApplicationService(
        settings=Settings(
            _env_file=None,
            ENABLE_PUBLIC_EXCHANGE_DATA=False,
            REPOSITORY_BACKEND="memory",
            TRADING_MODE="dry_run",
            LIVE_TRADING_ENABLED=False,
            BINANCE_API_KEY="key",
            BINANCE_API_SECRET="secret",
            BINANCE_SPOT_TRADING_ENABLED=True,
        ),
        portfolio_repository=FundedPortfolioRepository(),
        strategy_repository=EmptyStrategyRepository(),
        audit_log_repository=audit_repository,
        risk_repository=EmptyRiskRepository(),
        ai_analysis_repository=EmptyAiAnalysisRepository(),
        system_state_repository=EmptySystemStateRepository(),
    )
    service._private_exchange_request_timeout_seconds = lambda: 0.01
    service._risk_market_context = lambda: MarketOverview(
        symbol="BTC/USDT",
        timeframe="1h",
        exchange=ExchangeId.BINANCE,
        last_price=51_000,
        change_24h_percent=1,
        volume_24h=1000,
        volatility=1,
        rsi=50,
        data_latency_seconds=0,
        data_integrity="local_cache",
        candles=[],
    )

    dashboard = service.get_dashboard()

    equity_metric = next(metric for metric in dashboard.metrics if metric.label == "资产净值")
    assert calls == [ExchangeId.BINANCE]
    assert equity_metric.value == "$1,051.00"
    assert equity_metric.detail == "from portfolio repository"
    assert "timed out" in audit_repository.list_logs(limit=1)[0].message


def test_dashboard_uses_live_portfolio_snapshot_for_equity_and_positions(monkeypatch) -> None:
    class StubTradingClient:
        def get_balances(self) -> list[Balance]:
            return [
                Balance(asset="BTC", free=0.01, locked=0, total=0.01),
                Balance(asset="USDT", free=100, locked=0, total=100),
            ]

        def get_open_orders(self) -> list[Order]:
            return []

    def stub_client(exchange, settings):
        assert exchange == ExchangeId.BINANCE
        assert settings.binance_spot_trading_enabled is True
        return StubTradingClient()

    monkeypatch.setattr("app.application.workbench.get_spot_trading_client", stub_client)

    service = WorkbenchApplicationService(
        settings=Settings(
            _env_file=None,
            ENABLE_PUBLIC_EXCHANGE_DATA=False,
            REPOSITORY_BACKEND="memory",
            TRADING_MODE="live",
            LIVE_TRADING_ENABLED=True,
            BINANCE_API_KEY="key",
            BINANCE_API_SECRET="secret",
            BINANCE_SPOT_TRADING_ENABLED=True,
        ),
        portfolio_repository=EmptyPortfolioRepository(),
        strategy_repository=EmptyStrategyRepository(),
        audit_log_repository=EmptyAuditLogRepository(),
        risk_repository=EmptyRiskRepository(),
        ai_analysis_repository=EmptyAiAnalysisRepository(),
        system_state_repository=EmptySystemStateRepository(),
    )
    service.ai_service = LowRiskAiService()
    service.get_ai_analysis = service.ai_service.analyze_empty_context
    service._safe_spot_price = lambda exchange, symbol: 50_000 if symbol == "BTC/USDT" else None
    service._risk_market_context = lambda: MarketOverview(
        symbol="BTC/USDT",
        timeframe="1h",
        exchange=ExchangeId.BINANCE,
        last_price=50_000,
        change_24h_percent=1,
        volume_24h=1000,
        volatility=1,
        rsi=50,
        data_latency_seconds=0,
        data_integrity="live_public",
        candles=[],
    )

    dashboard = service.get_dashboard()
    trading = service.get_trading_summary()

    equity_metric = next(metric for metric in dashboard.metrics if metric.label == "资产净值")
    position_metric = next(metric for metric in dashboard.metrics if metric.label == "当前仓位")
    balance_rule = next(rule for rule in service.get_risk_status().rules if rule.name == "账户余额来源")

    assert equity_metric.value == "$600.00"
    assert equity_metric.detail == "from live account snapshot"
    assert position_metric.value == "1"
    assert [position.symbol for position in dashboard.positions] == ["BTC/USDT"]
    assert [balance.asset for balance in trading.balances] == ["BTC", "USDT"]
    assert balance_rule.current_value == "2 balances"


def test_default_strategies_are_system_configs_not_account_data() -> None:
    strategies = make_service().get_strategies()
    strategy_by_id = {strategy.id: strategy for strategy in strategies}
    strategy_ids = {strategy.id for strategy in strategies}

    assert strategy_ids >= {
        "ma_cross",
        "rsi_mean_reversion",
        "grid",
        "breakout",
        "bollinger_bands",
        "macd_trend",
        "trend_pullback",
        "dca",
        "funding_rate_guard",
        "ai_filter",
    }
    assert strategy_by_id["ma_cross"].enabled is True
    assert strategy_by_id["grid"].supports_backtest is True
    assert strategy_by_id["breakout"].supports_backtest is True
    assert strategy_by_id["dca"].supports_signals is False
    assert strategy_by_id["funding_rate_guard"].supports_backtest is False
    assert strategy_by_id["ai_filter"].supports_signals is False
    assert all(strategy.recent_signals == [] for strategy in strategies)


def test_signal_engine_generates_enabled_strategy_signals() -> None:
    service = make_service()
    service.get_market_overview = lambda **_: MarketOverview(  # type: ignore[method-assign]
        symbol="BTC/USDT",
        exchange=ExchangeId.BINANCE,
        timeframe="1h",
        last_price=100,
        change_24h_percent=0,
        volume_24h=0,
        volatility=0,
        rsi=50,
        data_latency_seconds=0,
        data_integrity="live_public",
        candles=[
            *make_candles([110, 108, 106, 104, 102, 100, 98, 96, 94, 92, 90, 92, 94, 96, 98, 100, 102]),
        ],
    )

    service.update_strategy(
        "ma_cross",
        StrategyUpdateRequest(parameters={"fast_window": 2, "slow_window": 3}),
    )

    signals = service.generate_strategy_signals(symbol="BTC/USDT")

    assert {signal.strategy for signal in signals} >= {"ma_cross", "rsi_mean_reversion"}
    assert all(signal.action in SpotSignalAction for signal in signals)
    assert service.get_strategies()[0].recent_signals


def test_system_status_does_not_fabricate_public_market_latency() -> None:
    status = make_service().get_system_status()

    assert status.data_latency_seconds is None
    assert all(exchange.latency_ms is None for exchange in status.exchanges)
    assert all(exchange.state == ConnectionState.OFFLINE for exchange in status.exchanges)


def test_system_status_uses_public_market_probe_for_latency() -> None:
    _SYSTEM_MARKET_STATUS_CACHE.clear()
    checked_at = utc_now()
    seen: list[ExchangeId] = []
    service = WorkbenchApplicationService(
        settings=Settings(
            _env_file=None,
            ENABLE_PUBLIC_EXCHANGE_DATA=True,
            REPOSITORY_BACKEND="memory",
            BINANCE_SPOT_BASE_URL="https://binance.test",
            OKX_REST_BASE_URL="https://okx.test",
        ),
        portfolio_repository=EmptyPortfolioRepository(),
        strategy_repository=EmptyStrategyRepository(),
        audit_log_repository=EmptyAuditLogRepository(),
        risk_repository=EmptyRiskRepository(),
        ai_analysis_repository=EmptyAiAnalysisRepository(),
        system_state_repository=EmptySystemStateRepository(),
    )

    def probe(exchange: ExchangeId) -> tuple[ExchangeStatus, datetime]:
        seen.append(exchange)
        latency_ms = 123 if exchange == ExchangeId.BINANCE else 234
        return (
            ExchangeStatus(
                exchange=exchange,
                state=ConnectionState.HEALTHY,
                latency_ms=latency_ms,
                last_checked_at=checked_at,
                message="checked",
            ),
            checked_at,
        )

    service._probe_public_exchange_status = probe  # type: ignore[method-assign]

    status = service.get_system_status()

    assert seen == [ExchangeId.BINANCE, ExchangeId.OKX]
    assert status.data_latency_seconds == 0
    assert {exchange.exchange: exchange.latency_ms for exchange in status.exchanges} == {
        ExchangeId.BINANCE: 123,
        ExchangeId.OKX: 234,
    }
    _SYSTEM_MARKET_STATUS_CACHE.clear()


def test_public_market_probe_success_reports_healthy_status() -> None:
    service = make_service()
    service._request_public_ticker_probe = lambda exchange: None  # type: ignore[method-assign]

    status, checked_at = service._probe_public_exchange_status(ExchangeId.BINANCE)

    assert checked_at is not None
    assert status.state == ConnectionState.HEALTHY
    assert status.latency_ms is not None
    assert status.latency_ms > 0


def test_strategy_update_is_persisted_and_audited() -> None:
    service = make_service()

    updated = service.update_strategy(
        "ma_cross",
        StrategyUpdateRequest(parameters={"fast_window": 5, "slow_window": 20}),
    )

    assert updated.parameters == {"fast_window": 5, "slow_window": 20}
    ma_cross = next(strategy for strategy in service.get_strategies() if strategy.id == "ma_cross")
    assert ma_cross.parameters == {"fast_window": 5, "slow_window": 20}
    assert service.get_logs(limit=10)[0].module == "strategy"


def test_backtest_returns_data_unavailable_without_public_market_data() -> None:
    result = make_service().run_backtest(request=BacktestRequest())

    assert result.status == "data_unavailable"
    assert result.trades == []


def test_dry_run_order_is_rejected_by_risk_without_balance_source_and_audited() -> None:
    service = make_service()

    order = service.create_dry_run_order(
        DryRunOrderRequest(symbol="BTC/USDT", action=SpotSignalAction.BUY, quantity=0.01),
    )

    assert order.status == "rejected_by_risk:no_new_positions"
    assert service.get_trading_summary().historical_orders == [order]
    assert service.get_logs(limit=1)[0].module == "trading"


def test_dry_run_order_builds_traceable_strategy_ai_risk_trading_chain() -> None:
    service = make_service()

    order = service.create_dry_run_order(
        DryRunOrderRequest(
            symbol="BTC/USDT",
            action=SpotSignalAction.BUY,
            quantity=0.01,
            price=50_000,
            strategy="ma_cross",
        ),
    )
    assert order.correlation_id is not None

    trace = service.get_trade_decision_trace(order.correlation_id)

    assert trace.correlation_id == order.correlation_id
    assert trace.signal is not None
    assert trace.signal.strategy == "ma_cross"
    assert trace.signal.blocked_by == "risk:no_new_positions"
    assert trace.ai_analysis is not None
    assert trace.ai_analysis.correlation_id == order.correlation_id
    assert trace.risk_status == "no_new_positions"
    assert trace.order == order
    assert {log.module for log in trace.logs} >= {"strategy", "ai", "risk", "trading"}
    assert {event.correlation_id for event in trace.risk_events} == {order.correlation_id}


def test_live_order_requires_global_and_exchange_enablement() -> None:
    service = make_service()

    try:
        service.create_live_order(
            LiveOrderRequest(symbol="BTC/USDT", action=SpotSignalAction.BUY, quantity=0.01),
        )
    except ValueError as exc:
        message = str(exc)
    else:
        raise AssertionError("live order should require explicit enablement")

    assert "TRADING_MODE=live" in message


def test_live_order_submits_through_configured_spot_client_and_audits(monkeypatch) -> None:
    service = make_live_service()
    seen: dict[str, object] = {}

    class FakeTradingClient:
        def create_order(self, request) -> Order:
            seen["request"] = request
            return Order(
                exchange=ExchangeId.BINANCE,
                order_id="EX-1",
                symbol=request.symbol,
                side=request.side,
                order_type=request.order_type,
                price=request.price or 0,
                quantity=request.quantity,
                status="open",
                created_at=utc_now(),
            )

        def get_balances(self):
            return [Balance(asset="USDT", free=1000, locked=0, total=1000)]

        def get_open_orders(self, symbol=None):
            return []

    monkeypatch.setattr(
        "app.application.workbench.get_spot_trading_client",
        lambda *_args, **_kwargs: FakeTradingClient(),
    )

    order = service.create_live_order(
        LiveOrderRequest(
            exchange=ExchangeId.BINANCE,
            symbol="BTC/USDT",
            action=SpotSignalAction.BUY,
            order_type="limit",
            quantity=0.001,
            price=50_000,
        ),
    )

    assert order.order_id == "EX-1"
    assert order.exchange == ExchangeId.BINANCE
    assert order.correlation_id is not None
    assert seen["request"].side == "buy"
    assert service.get_trading_summary().historical_orders == [order]
    assert service.get_logs(limit=1)[0].message.startswith("Live spot order submitted")


def test_cancel_live_order_uses_exchange_client_and_persists_audit(monkeypatch) -> None:
    service = make_live_service()
    seen: dict[str, object] = {}

    class FakeTradingClient:
        def cancel_order(self, symbol: str, order_id: str) -> Order:
            seen.update({"symbol": symbol, "order_id": order_id})
            return Order(
                exchange=ExchangeId.BINANCE,
                order_id=order_id,
                symbol=symbol,
                side="cancel_order",
                order_type="cancel",
                price=0,
                quantity=0,
                status="canceled",
                created_at=utc_now(),
            )

    monkeypatch.setattr(
        "app.application.workbench.get_spot_trading_client",
        lambda *_args, **_kwargs: FakeTradingClient(),
    )

    order = service.cancel_live_order(
        LiveCancelOrderRequest(exchange=ExchangeId.BINANCE, symbol="BTC/USDT", order_id="EX-1"),
    )

    assert seen == {"symbol": "BTC/USDT", "order_id": "EX-1"}
    assert order.status == "canceled"
    assert order.side == "cancel_order"
    assert service.get_logs(limit=1)[0].message.startswith("Live spot order canceled")


def test_manual_close_position_sells_existing_position_quantity(monkeypatch) -> None:
    service = make_live_service()
    seen: dict[str, object] = {}

    class FakeTradingClient:
        def create_order(self, request) -> Order:
            seen["request"] = request
            return Order(
                exchange=ExchangeId.BINANCE,
                order_id="CLOSE-1",
                symbol=request.symbol,
                side=request.side,
                order_type=request.order_type,
                price=0,
                quantity=request.quantity,
                status="closed",
                created_at=utc_now(),
            )

    monkeypatch.setattr(
        "app.application.workbench.get_spot_trading_client",
        lambda *_args, **_kwargs: FakeTradingClient(),
    )

    order = service.close_live_position(
        ManualClosePositionRequest(exchange=ExchangeId.BINANCE, symbol="BTC/USDT"),
    )

    assert order.side == "sell"
    assert order.quantity == 0.001
    assert seen["request"].side == "sell"
    assert seen["request"].quantity == 0.001


def test_settings_summary_reports_exchange_private_api_configuration() -> None:
    settings = make_live_service().get_settings_summary()

    binance = next(exchange for exchange in settings.exchanges if exchange["id"] == "binance")
    okx = next(exchange for exchange in settings.exchanges if exchange["id"] == "okx")

    assert binance["api_key_configured"] is True
    assert binance["spot_trading_enabled"] is True
    assert okx["api_key_configured"] is False
    assert okx["spot_trading_enabled"] is False


def test_settings_summary_lists_news_feed_sources() -> None:
    settings = make_service().get_settings_summary()

    feed_names = [feed.name for feed in settings.news_feeds]

    assert settings.data["news_feed_count"] == 8
    assert feed_names == [
        "CoinDesk",
        "Cointelegraph",
        "Decrypt",
        "The Block",
        "Blockworks",
        "CryptoSlate",
        "BeInCrypto",
        "NewsBTC",
    ]
    assert settings.news_feeds[0].website_url == "https://www.coindesk.com"
    assert settings.news_feeds[0].feed_url == "https://www.coindesk.com/arc/outboundfeeds/rss/"


def test_settings_summary_includes_common_ai_provider_templates() -> None:
    settings = make_service().get_settings_summary()

    templates = {template["id"]: template for template in settings.ai_provider_templates}

    for provider in [
        "openai_compatible",
        "openai",
        "deepseek",
        "dashscope",
        "moonshot",
        "zhipu",
        "minimax",
        "ollama",
        "aihubmix",
        "openrouter",
        "siliconflow",
    ]:
        assert provider in templates

    assert templates["openai"]["default_model"] == "gpt-5.5"
    assert templates["deepseek"]["default_model"] == "deepseek-v4-pro"
    assert templates["dashscope"]["base_url"] == "https://dashscope.aliyuncs.com/compatible-mode/v1"
    assert templates["dashscope"]["default_model"] == "qwen3.7-max"
    assert templates["moonshot"]["base_url"] == "https://api.moonshot.ai/v1"
    assert templates["moonshot"]["default_model"] == "kimi-k2.7-code"
    assert templates["zhipu"]["base_url"] == "https://api.z.ai/api/paas/v4"
    assert templates["zhipu"]["default_model"] == "glm-5.2"
    assert templates["minimax"]["default_model"] == "MiniMax-M3"
    assert templates["ollama"]["default_model"] == "qwen3.6"
    assert templates["ollama"]["requires_api_key"] is False
    assert templates["openrouter"]["default_model"] == "~openai/gpt-latest"
    assert templates["siliconflow"]["default_model"] == "Qwen/Qwen3.6-35B-A3B"


def test_ollama_settings_summary_marks_enabled_without_api_key() -> None:
    service = WorkbenchApplicationService(
        settings=Settings(
            _env_file=None,
            ENABLE_PUBLIC_EXCHANGE_DATA=False,
            REPOSITORY_BACKEND="memory",
            AI_PROXY_A_PROVIDER="ollama",
            AI_PROXY_A_BASE_URL="http://127.0.0.1:11434/v1",
            AI_PROXY_A_API_KEY="",
            AI_PROXY_A_MODEL="qwen3.6",
            AI_PROXY_A_ENABLED=True,
            AI_PROXY_A_API_FORMAT="chat_completions",
        ),
        portfolio_repository=EmptyPortfolioRepository(),
        strategy_repository=EmptyStrategyRepository(),
        audit_log_repository=EmptyAuditLogRepository(),
        risk_repository=EmptyRiskRepository(),
        ai_analysis_repository=EmptyAiAnalysisRepository(),
        system_state_repository=EmptySystemStateRepository(),
    )

    settings = service.get_settings_summary()
    proxy_a = settings.ai_proxies[0]

    assert proxy_a["id"] == "ollama"
    assert proxy_a["enabled"] is True
    assert proxy_a["api_key_configured"] is False
    assert proxy_a["requires_api_key"] is False


def test_settings_summary_does_not_enable_proxy_without_base_url() -> None:
    service = WorkbenchApplicationService(
        settings=Settings(
            _env_file=None,
            ENABLE_PUBLIC_EXCHANGE_DATA=False,
            REPOSITORY_BACKEND="memory",
            AI_PROXY_A_PROVIDER="ollama",
            AI_PROXY_A_BASE_URL="",
            AI_PROXY_A_API_KEY="",
            AI_PROXY_A_MODEL="qwen3.6",
            AI_PROXY_A_ENABLED=True,
            AI_PROXY_A_API_FORMAT="chat_completions",
        ),
        portfolio_repository=EmptyPortfolioRepository(),
        strategy_repository=EmptyStrategyRepository(),
        audit_log_repository=EmptyAuditLogRepository(),
        risk_repository=EmptyRiskRepository(),
        ai_analysis_repository=EmptyAiAnalysisRepository(),
        system_state_repository=EmptySystemStateRepository(),
    )

    assert service.get_settings_summary().ai_proxies[0]["enabled"] is False


def test_update_ai_proxy_settings_writes_env_file_and_returns_summary(tmp_path, monkeypatch) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text(
        "\n".join(
            [
                "AI_PROXY_A_PROVIDER=right_code",
                "AI_PROXY_A_BASE_URL=https://www.right.codes/codex/v1",
                "AI_PROXY_A_API_KEY=old",
                "AI_PROXY_A_MODEL=gpt-5.5",
                "AI_PROXY_A_PRIORITY=1",
                "AI_PROXY_A_ENABLED=true",
                "AI_PROXY_A_API_FORMAT=responses",
            ],
        )
        + "\n",
        encoding="utf-8",
    )
    monkeypatch.setattr("app.core.config.ROOT_ENV_FILE", env_file)

    service = make_service()
    summary = service.update_ai_proxy_settings(
        AiProxySettingsUpdateRequest(
            proxies=[
                AiProxySettingsUpdate(
                    slot="A",
                    provider="minimax",
                    base_url="https://api.minimax.io/v1",
                    api_key="new-key",
                    model="MiniMax-M2.7",
                    priority=1,
                    enabled=True,
                    api_format="chat_completions",
                ),
            ],
        ),
    )

    env_text = env_file.read_text(encoding="utf-8")
    assert "AI_PROXY_A_PROVIDER=minimax" in env_text
    assert "AI_PROXY_A_BASE_URL=https://api.minimax.io/v1" in env_text
    assert "AI_PROXY_A_API_KEY=new-key" in env_text
    assert "AI_PROXY_A_MODEL=MiniMax-M2.7" in env_text
    assert summary.ai_proxies[0]["id"] == "minimax"
    assert summary.ai_proxies[0]["base_url"] == "https://api.minimax.io/v1"
    assert summary.ai_proxies[0]["model"] == "MiniMax-M2.7"
    assert summary.ai_proxies[0]["enabled"] is True
    assert summary.ai_proxies[0]["api_key_configured"] is True
    assert summary.ai_provider_templates


def test_ai_proxy_connection_test_uses_saved_key_and_validates_model(monkeypatch) -> None:
    seen: dict[str, object] = {}

    class StubAiService:
        def __init__(self, proxy, timeout_seconds):
            seen["proxy"] = proxy
            seen["timeout_seconds"] = timeout_seconds
            self.provider = proxy.provider
            self.model = proxy.model

        def analyze_empty_context(self) -> AiAnalysis:
            return AiAnalysis(
                market_regime="range",
                sentiment_score=0,
                risk_level=RiskLevel.LOW,
                event_risk=False,
                allowed_direction=AllowedDirection.BOTH,
                confidence=0.7,
                provider=self.provider,
                model=self.model,
                rationale=[],
                structured_payload={},
            )

    monkeypatch.setattr("app.application.workbench.OpenAiCompatibleAiService", StubAiService)

    service = WorkbenchApplicationService(
        settings=Settings(
            _env_file=None,
            ENABLE_PUBLIC_EXCHANGE_DATA=False,
            REPOSITORY_BACKEND="memory",
            AI_PROXY_A_PROVIDER="deepseek",
            AI_PROXY_A_API_KEY="saved-key",
        ),
        portfolio_repository=EmptyPortfolioRepository(),
        strategy_repository=EmptyStrategyRepository(),
        audit_log_repository=EmptyAuditLogRepository(),
        risk_repository=EmptyRiskRepository(),
        ai_analysis_repository=EmptyAiAnalysisRepository(),
        system_state_repository=EmptySystemStateRepository(),
    )

    result = service.test_ai_proxy_connection(
        AiProxyConnectionTestRequest(
            proxy=AiProxySettingsUpdate(
                slot="A",
                provider="deepseek",
                base_url="https://api.deepseek.com",
                api_key=None,
                model="deepseek-v4-pro",
                priority=1,
                enabled=True,
                api_format="chat_completions",
            ),
            timeout_seconds=7,
        ),
    )

    proxy = seen["proxy"]
    assert result.success is True
    assert result.provider == "deepseek"
    assert result.model == "deepseek-v4-pro"
    assert result.used_saved_api_key is True
    assert result.latency_ms >= 0
    assert seen["timeout_seconds"] == 7
    assert proxy.api_key == "saved-key"


def test_ai_proxy_connection_test_returns_readable_failure(monkeypatch) -> None:
    class FailingAiService:
        def __init__(self, proxy, timeout_seconds):
            pass

        def analyze_empty_context(self) -> AiAnalysis:
            raise AiServiceUnavailable("deepseek AI call failed: unauthorized")

    monkeypatch.setattr("app.application.workbench.OpenAiCompatibleAiService", FailingAiService)

    result = make_service().test_ai_proxy_connection(
        AiProxyConnectionTestRequest(
            proxy=AiProxySettingsUpdate(
                slot="B",
                provider="deepseek",
                base_url="https://api.deepseek.com",
                api_key="bad-key",
                model="deepseek-v4-pro",
                priority=2,
                enabled=True,
                api_format="chat_completions",
            ),
        ),
    )

    assert result.success is False
    assert result.provider == "deepseek"
    assert "unauthorized" in result.message


def test_ai_proxy_connection_test_requires_key_for_cloud_provider() -> None:
    result = make_service().test_ai_proxy_connection(
        AiProxyConnectionTestRequest(
            proxy=AiProxySettingsUpdate(
                slot="B",
                provider="deepseek",
                base_url="https://api.deepseek.com",
                api_key=None,
                model="deepseek-v4-pro",
                priority=2,
                enabled=True,
                api_format="chat_completions",
            ),
        ),
    )

    assert result.success is False
    assert "API Key" in result.message


def test_update_exchange_account_settings_writes_env_file_and_returns_summary(tmp_path, monkeypatch) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text(
        "\n".join(
            [
                "REPOSITORY_BACKEND=memory",
                "ENABLE_PUBLIC_EXCHANGE_DATA=false",
                "BINANCE_API_KEY=old-key",
                "BINANCE_API_SECRET=old-secret",
                "BINANCE_SPOT_TRADING_ENABLED=false",
                "BINANCE_SANDBOX=false",
            ],
        )
        + "\n",
        encoding="utf-8",
    )
    monkeypatch.setattr("app.core.config.ROOT_ENV_FILE", env_file)

    service = WorkbenchApplicationService(
        settings=Settings(_env_file=env_file),
        portfolio_repository=EmptyPortfolioRepository(),
        strategy_repository=EmptyStrategyRepository(),
        audit_log_repository=EmptyAuditLogRepository(),
        risk_repository=EmptyRiskRepository(),
        ai_analysis_repository=EmptyAiAnalysisRepository(),
        system_state_repository=EmptySystemStateRepository(),
    )
    summary = service.update_exchange_account_settings(
        ExchangeAccountSettingsUpdateRequest(
            accounts=[
                ExchangeAccountSettingsUpdate(
                    exchange=ExchangeId.BINANCE,
                    api_key=None,
                    api_secret="new-secret",
                    spot_trading_enabled=True,
                    sandbox=True,
                ),
            ],
        ),
    )

    env_text = env_file.read_text(encoding="utf-8")
    assert "BINANCE_API_KEY=old-key" in env_text
    assert "BINANCE_API_SECRET=new-secret" in env_text
    assert "BINANCE_SPOT_TRADING_ENABLED=true" in env_text
    assert "BINANCE_SANDBOX=true" in env_text

    binance = next(exchange for exchange in summary.exchanges if exchange["id"] == "binance")
    assert binance["api_key_configured"] is True
    assert binance["spot_trading_enabled"] is True
    assert binance["sandbox"] is True


def test_update_exchange_account_settings_rejects_enabled_account_without_credentials() -> None:
    service = make_service()

    with pytest.raises(ValueError, match="OKX_API_KEY"):
        service.update_exchange_account_settings(
            ExchangeAccountSettingsUpdateRequest(
                accounts=[
                    ExchangeAccountSettingsUpdate(
                        exchange=ExchangeId.OKX,
                        api_key="okx-key",
                        api_secret="",
                        passphrase="",
                        spot_trading_enabled=True,
                    ),
                ],
            ),
        )


def test_exchange_account_connection_test_uses_saved_credentials(monkeypatch) -> None:
    seen: dict[str, object] = {}

    class StubTradingClient:
        def __init__(self, **kwargs):
            seen.update(kwargs)

        def get_balances(self) -> list[Balance]:
            return [
                Balance(asset="BTC", free=0.1, locked=0, total=0.1),
                Balance(asset="USDT", free=100, locked=0, total=100),
            ]

    monkeypatch.setattr("app.application.workbench.CcxtSpotTradingClient", StubTradingClient)

    service = WorkbenchApplicationService(
        settings=Settings(
            _env_file=None,
            ENABLE_PUBLIC_EXCHANGE_DATA=False,
            REPOSITORY_BACKEND="memory",
            OKX_API_KEY="saved-key",
            OKX_API_SECRET="saved-secret",
            OKX_API_PASSPHRASE="saved-passphrase",
        ),
        portfolio_repository=EmptyPortfolioRepository(),
        strategy_repository=EmptyStrategyRepository(),
        audit_log_repository=EmptyAuditLogRepository(),
        risk_repository=EmptyRiskRepository(),
        ai_analysis_repository=EmptyAiAnalysisRepository(),
        system_state_repository=EmptySystemStateRepository(),
    )

    result = service.test_exchange_account_connection(
        ExchangeAccountConnectionTestRequest(
            account=ExchangeAccountSettingsUpdate(
                exchange=ExchangeId.OKX,
                api_key=None,
                api_secret=None,
                passphrase=None,
                spot_trading_enabled=True,
                sandbox=True,
            ),
            timeout_seconds=9,
        ),
    )

    assert result.success is True
    assert result.exchange == ExchangeId.OKX
    assert result.used_saved_credentials is True
    assert result.balance_asset_count == 2
    assert seen["exchange_id"] == "okx"
    assert seen["api_key"] == "saved-key"
    assert seen["api_secret"] == "saved-secret"
    assert seen["password"] == "saved-passphrase"
    assert seen["sandbox"] is True
    assert seen["timeout_seconds"] == 9


def test_binance_account_connection_test_uses_signed_account_probe(monkeypatch) -> None:
    seen: dict[str, object] = {}

    class StubResponse:
        status_code = 200

        def json(self):
            return {
                "balances": [
                    {"asset": "BTC", "free": "0.1", "locked": "0"},
                    {"asset": "ETH", "free": "0", "locked": "0"},
                    {"asset": "USDT", "free": "0", "locked": "3.2"},
                ],
            }

    class StubHttpClient:
        def __init__(self, base_url, timeout, headers):
            seen["base_url"] = base_url
            seen["timeout"] = timeout
            seen["headers"] = headers

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback):
            return None

        def get(self, path, params):
            seen["path"] = path
            seen["params"] = params
            return StubResponse()

    monkeypatch.setattr("app.application.workbench.httpx.Client", StubHttpClient)
    result = make_service().test_exchange_account_connection(
        ExchangeAccountConnectionTestRequest(
            account=ExchangeAccountSettingsUpdate(
                exchange=ExchangeId.BINANCE,
                api_key="binance-key",
                api_secret="binance-secret",
                spot_trading_enabled=True,
                sandbox=False,
            ),
            timeout_seconds=4,
        ),
    )

    assert result.success is True
    assert result.exchange == ExchangeId.BINANCE
    assert result.balance_asset_count == 2
    assert seen["path"] == "/api/v3/account"
    assert seen["headers"] == {"X-MBX-APIKEY": "binance-key"}
    assert "signature=" in str(seen["params"])


def test_exchange_account_connection_test_requires_credentials() -> None:
    result = make_service().test_exchange_account_connection(
        ExchangeAccountConnectionTestRequest(
            account=ExchangeAccountSettingsUpdate(
                exchange=ExchangeId.OKX,
                api_key="okx-key",
                api_secret="",
                passphrase="",
                spot_trading_enabled=True,
                sandbox=False,
            ),
        ),
    )

    assert result.success is False
    assert "API Secret" in result.message
    assert "Passphrase" in result.message


def test_okx_exchange_account_connection_test_returns_readable_failure(monkeypatch) -> None:
    class FailingTradingClient:
        def __init__(self, **kwargs):
            pass

        def get_balances(self) -> list[Balance]:
            raise ExchangeTradingError(
                "binance GET https://api.binance.com/sapi/v1/capital/config/getall"
                "?timestamp=1782569996074&recvWindow=10000&signature=secret-signature"
                " invalid api key",
            )

    monkeypatch.setattr("app.application.workbench.CcxtSpotTradingClient", FailingTradingClient)

    result = make_service().test_exchange_account_connection(
        ExchangeAccountConnectionTestRequest(
            account=ExchangeAccountSettingsUpdate(
                exchange=ExchangeId.OKX,
                api_key="bad-key",
                api_secret="bad-secret",
                passphrase="bad-passphrase",
                spot_trading_enabled=True,
                sandbox=False,
            ),
        ),
    )

    assert result.success is False
    assert result.exchange == ExchangeId.OKX
    assert "invalid api key" in result.message
    assert "secret-signature" not in result.message
    assert "timestamp=1782569996074" not in result.message


def test_binance_account_connection_test_returns_auth_failure_without_leaking_signature(monkeypatch) -> None:
    class StubResponse:
        status_code = 401

        def json(self):
            return {"code": -2015, "msg": "Invalid API-key, IP, or permissions for action."}

    class StubHttpClient:
        def __init__(self, base_url, timeout, headers):
            pass

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback):
            return None

        def get(self, path, params):
            return StubResponse()

    monkeypatch.setattr("app.application.workbench.httpx.Client", StubHttpClient)
    result = make_service().test_exchange_account_connection(
        ExchangeAccountConnectionTestRequest(
            account=ExchangeAccountSettingsUpdate(
                exchange=ExchangeId.BINANCE,
                api_key="bad-key",
                api_secret="bad-secret",
                spot_trading_enabled=True,
                sandbox=False,
            ),
        ),
    )

    assert result.success is False
    assert "Invalid API-key" in result.message
    assert "signature" not in result.message


def test_update_notification_settings_writes_env_file_and_returns_summary(tmp_path, monkeypatch) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text(
        "\n".join(
            [
                "REPOSITORY_BACKEND=memory",
                "ENABLE_PUBLIC_EXCHANGE_DATA=false",
                "WECOM_WEBHOOK_URL=https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=old",
                "TELEGRAM_BOT_TOKEN=old-token",
                "TELEGRAM_CHAT_ID=old-chat",
                "DISCORD_WEBHOOK_URL=https://discord.com/api/webhooks/old",
                "EMAIL_SMTP_PORT=465",
                "EMAIL_USE_TLS=false",
            ],
        )
        + "\n",
        encoding="utf-8",
    )
    monkeypatch.setattr("app.core.config.ROOT_ENV_FILE", env_file)

    service = WorkbenchApplicationService(
        settings=Settings(_env_file=env_file),
        portfolio_repository=EmptyPortfolioRepository(),
        strategy_repository=EmptyStrategyRepository(),
        audit_log_repository=EmptyAuditLogRepository(),
        risk_repository=EmptyRiskRepository(),
        ai_analysis_repository=EmptyAiAnalysisRepository(),
        system_state_repository=EmptySystemStateRepository(),
    )
    summary = service.update_notification_settings(
        NotificationSettingsUpdateRequest(
            channels=[
                NotificationChannelSettingsUpdate(
                    provider=NotificationProvider.WECOM,
                    webhook_url=None,
                ),
                NotificationChannelSettingsUpdate(
                    provider=NotificationProvider.TELEGRAM,
                    telegram_bot_token="new-token",
                    telegram_chat_id=None,
                ),
                NotificationChannelSettingsUpdate(
                    provider=NotificationProvider.EMAIL,
                    email_smtp_host="smtp.example.com",
                    email_smtp_port=2525,
                    email_smtp_username="",
                    email_smtp_password="mail-pass",
                    email_from="bot@example.com",
                    email_to="ops@example.com",
                    email_use_tls=True,
                ),
                NotificationChannelSettingsUpdate(
                    provider=NotificationProvider.SLACK,
                    webhook_url="https://hooks.slack.com/services/test",
                ),
                NotificationChannelSettingsUpdate(
                    provider=NotificationProvider.DISCORD,
                    webhook_url="",
                ),
            ],
        ),
    )

    env_text = env_file.read_text(encoding="utf-8")
    assert "WECOM_WEBHOOK_URL=https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=old" in env_text
    assert "TELEGRAM_BOT_TOKEN=new-token" in env_text
    assert "TELEGRAM_CHAT_ID=old-chat" in env_text
    assert "EMAIL_SMTP_HOST=smtp.example.com" in env_text
    assert "EMAIL_SMTP_PORT=2525" in env_text
    assert "EMAIL_SMTP_USERNAME=" in env_text
    assert "EMAIL_SMTP_PASSWORD=mail-pass" in env_text
    assert "EMAIL_FROM=bot@example.com" in env_text
    assert "EMAIL_TO=ops@example.com" in env_text
    assert "EMAIL_USE_TLS=true" in env_text
    assert "SLACK_WEBHOOK_URL=https://hooks.slack.com/services/test" in env_text
    assert "DISCORD_WEBHOOK_URL=" in env_text

    assert summary.notifications["wecom_webhook"] is True
    assert summary.notifications["telegram_bot"] is True
    assert summary.notifications["email_smtp"] is True
    assert summary.notifications["email_smtp_port"] == 2525
    assert summary.notifications["email_use_tls"] is True
    assert summary.notifications["slack_webhook"] is True
    assert summary.notifications["discord_webhook"] is False


def test_update_daily_push_settings_writes_env_file_and_returns_summary(tmp_path, monkeypatch) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text(
        "\n".join(
            [
                "REPOSITORY_BACKEND=memory",
                "ENABLE_PUBLIC_EXCHANGE_DATA=false",
                "SCHEDULE_ENABLED=false",
                "SCHEDULE_TIME=18:00",
                "SCHEDULE_RUN_IMMEDIATELY=false",
            ],
        )
        + "\n",
        encoding="utf-8",
    )
    monkeypatch.setattr("app.core.config.ROOT_ENV_FILE", env_file)

    service = WorkbenchApplicationService(
        settings=Settings(_env_file=env_file),
        portfolio_repository=EmptyPortfolioRepository(),
        strategy_repository=EmptyStrategyRepository(),
        audit_log_repository=EmptyAuditLogRepository(),
        risk_repository=EmptyRiskRepository(),
        ai_analysis_repository=EmptyAiAnalysisRepository(),
        system_state_repository=EmptySystemStateRepository(),
    )
    summary = service.update_daily_push_settings(
        DailyPushSettingsUpdateRequest(
            enabled=True,
            schedule_time="09:30",
            schedule_times="09:30,18:00",
            run_immediately=True,
        ),
    )

    env_text = env_file.read_text(encoding="utf-8")
    assert "SCHEDULE_ENABLED=true" in env_text
    assert "SCHEDULE_TIME=09:30" in env_text
    assert "SCHEDULE_TIMES=09:30,18:00" in env_text
    assert "SCHEDULE_RUN_IMMEDIATELY=true" in env_text
    assert summary.data["schedule_enabled"] == "true"
    assert summary.data["schedule_time"] == "09:30"
    assert summary.data["schedule_times"] == "09:30,18:00"
    assert summary.data["schedule_run_immediately"] == "true"


def test_stale_market_data_blocks_dry_run_opening_and_persists_risk_event(monkeypatch) -> None:
    service = WorkbenchApplicationService(
        settings=Settings(
            _env_file=None,
            ENABLE_PUBLIC_EXCHANGE_DATA=False,
            REPOSITORY_BACKEND="memory",
            MAX_DATA_LATENCY_SECONDS=300,
        ),
        portfolio_repository=FundedPortfolioRepository(),
        strategy_repository=EmptyStrategyRepository(),
        audit_log_repository=EmptyAuditLogRepository(),
        risk_repository=EmptyRiskRepository(),
        ai_analysis_repository=EmptyAiAnalysisRepository(),
        system_state_repository=EmptySystemStateRepository(),
    )
    service.ai_service = LowRiskAiService()
    service.get_ai_analysis = service.ai_service.analyze_empty_context
    monkeypatch.setattr(
        service,
        "_risk_market_context",
        lambda: MarketOverview(
            symbol="BTC/USDT",
            timeframe="1h",
            exchange=ExchangeId.BINANCE,
            last_price=0,
            change_24h_percent=0,
            volume_24h=0,
            volatility=0,
            rsi=0,
            data_latency_seconds=301,
            data_integrity="live_public",
            candles=[],
        ),
    )

    order = service.create_dry_run_order(
        DryRunOrderRequest(symbol="BTC/USDT", action=SpotSignalAction.BUY, quantity=0.01),
    )

    assert order.status == "rejected_by_risk:no_new_positions"
    assert any(event.rule == "数据延迟" for event in service.risk_repository.list_events())


def test_feishu_test_notification_returns_not_configured_and_audits() -> None:
    service = make_service()

    result = service.send_test_notification(NotificationTestRequest(message="test"))

    assert result.success is False
    assert "not configured" in result.message
    assert service.get_logs(limit=1)[0].module == "notification"


def test_settings_summary_reports_all_notification_channels() -> None:
    settings = make_service().get_settings_summary()

    assert settings.notifications == {
        "feishu_webhook": False,
        "wecom_webhook": False,
        "telegram_bot_token": False,
        "telegram_chat_id": False,
        "telegram_bot": False,
        "email_smtp_host": False,
        "email_smtp_port": 587,
        "email_smtp_username": False,
        "email_smtp_password": False,
        "email_from": False,
        "email_to": False,
        "email_use_tls": True,
        "email_smtp": False,
        "slack_webhook": False,
        "discord_webhook": False,
        "severity": "warning+",
    }


def test_wecom_test_notification_posts_markdown_payload(monkeypatch) -> None:
    seen: dict[str, object] = {}

    def fake_post(url: str, json: dict[str, object], timeout: int) -> httpx.Response:
        seen.update({"url": url, "json": json, "timeout": timeout})
        return httpx.Response(200, request=httpx.Request("POST", url))

    monkeypatch.setattr("app.application.notifications.httpx.post", fake_post)
    service = WorkbenchApplicationService(
        settings=Settings(
            _env_file=None,
            ENABLE_PUBLIC_EXCHANGE_DATA=False,
            REPOSITORY_BACKEND="memory",
            WECOM_WEBHOOK_URL="https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=test",
        ),
        portfolio_repository=EmptyPortfolioRepository(),
        strategy_repository=EmptyStrategyRepository(),
        audit_log_repository=EmptyAuditLogRepository(),
        risk_repository=EmptyRiskRepository(),
        ai_analysis_repository=EmptyAiAnalysisRepository(),
        system_state_repository=EmptySystemStateRepository(),
    )

    result = service.send_test_notification(
        NotificationTestRequest(
            provider=NotificationProvider.WECOM,
            title="DSA 通知测试",
            message="hello",
            timeout_seconds=7,
        ),
    )

    assert result.success is True
    assert seen["url"] == "https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=test"
    assert seen["json"] == {
        "msgtype": "markdown",
        "markdown": {"content": "**DSA 通知测试**\n\nhello"},
    }
    assert seen["timeout"] == 7


def test_webhook_notification_channels_post_expected_payloads(monkeypatch) -> None:
    sent: list[tuple[str, dict[str, object]]] = []

    def fake_post(url: str, json: dict[str, object], timeout: int) -> httpx.Response:
        sent.append((url, json))
        return httpx.Response(200, request=httpx.Request("POST", url))

    monkeypatch.setattr("app.application.notifications.httpx.post", fake_post)
    service = WorkbenchApplicationService(
        settings=Settings(
            _env_file=None,
            ENABLE_PUBLIC_EXCHANGE_DATA=False,
            REPOSITORY_BACKEND="memory",
            TELEGRAM_BOT_TOKEN="token",
            TELEGRAM_CHAT_ID="chat",
            SLACK_WEBHOOK_URL="https://hooks.slack.com/services/test",
            DISCORD_WEBHOOK_URL="https://discord.com/api/webhooks/test",
        ),
        portfolio_repository=EmptyPortfolioRepository(),
        strategy_repository=EmptyStrategyRepository(),
        audit_log_repository=EmptyAuditLogRepository(),
        risk_repository=EmptyRiskRepository(),
        ai_analysis_repository=EmptyAiAnalysisRepository(),
        system_state_repository=EmptySystemStateRepository(),
    )

    for provider in [
        NotificationProvider.TELEGRAM,
        NotificationProvider.SLACK,
        NotificationProvider.DISCORD,
    ]:
        result = service.send_test_notification(
            NotificationTestRequest(provider=provider, title="Alert", message="Ping"),
        )
        assert result.success is True

    assert sent == [
        (
            "https://api.telegram.org/bottoken/sendMessage",
            {"chat_id": "chat", "text": "Alert\nPing"},
        ),
        ("https://hooks.slack.com/services/test", {"text": "Alert\nPing"}),
        ("https://discord.com/api/webhooks/test", {"content": "Alert\nPing"}),
    ]


def test_news_sentiment_fetches_rss_scores_articles_and_feeds_ai_analysis() -> None:
    feed = """<?xml version="1.0" encoding="UTF-8"?>
    <rss version="2.0">
      <channel>
        <title>Crypto Test</title>
        <item>
          <title>Bitcoin crash after exchange hack and SEC lawsuit</title>
          <link>https://example.com/btc-risk</link>
          <pubDate>Sun, 14 Jun 2026 08:00:00 GMT</pubDate>
          <description>Liquidation risk rises after the exploit.</description>
        </item>
      </channel>
    </rss>
    """

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=feed)

    settings = Settings(
        _env_file=None,
        ENABLE_NEWS_SENTIMENT=True,
        NEWS_FEED_URLS="https://example.com/rss",
        REPOSITORY_BACKEND="memory",
    )
    service = WorkbenchApplicationService(
        settings=settings,
        portfolio_repository=EmptyPortfolioRepository(),
        strategy_repository=EmptyStrategyRepository(),
        audit_log_repository=EmptyAuditLogRepository(),
        risk_repository=EmptyRiskRepository(),
        ai_analysis_repository=EmptyAiAnalysisRepository(),
        system_state_repository=EmptySystemStateRepository(),
    )
    service.news_service = CryptoNewsService(
        settings=settings,
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )

    news = service.get_news_sentiment(symbol="BTC/USDT", refresh=True)
    analysis = service.get_ai_analysis()

    assert news.status == "ok"
    assert news.article_count == 1
    assert news.sentiment_score <= -0.5
    assert news.event_risk is True
    assert news.articles[0].matched_keywords
    assert analysis.market_regime == "news_negative"
    assert analysis.risk_level == RiskLevel.HIGH
    assert analysis.allowed_direction == AllowedDirection.NONE


def test_ai_analysis_falls_back_conservatively_when_proxy_times_out() -> None:
    class FailingAiService:
        provider = "right_code"
        model = "gpt-5.5"

        def analyze_empty_context(self, *args: object, **kwargs: object) -> AiAnalysis:
            raise AiServiceUnavailable("right_code AI call failed: timed out")

    service = make_service()
    service.ai_service = FailingAiService()
    service.get_news_sentiment(refresh=True)

    analysis = service.get_ai_analysis()

    assert analysis.provider == "right_code"
    assert analysis.market_regime == "ai_unavailable"
    assert analysis.risk_level == RiskLevel.HIGH
    assert analysis.allowed_direction == AllowedDirection.NONE
    assert analysis.event_risk is True
    assert "conservative fallback" in analysis.rationale[0]


def test_market_overview_prefers_live_exchange_data_over_local_cache(monkeypatch) -> None:
    service = WorkbenchApplicationService(
        settings=Settings(_env_file=None, REPOSITORY_BACKEND="mysql"),
        portfolio_repository=EmptyPortfolioRepository(),
        strategy_repository=EmptyStrategyRepository(),
        audit_log_repository=EmptyAuditLogRepository(),
        risk_repository=EmptyRiskRepository(),
        ai_analysis_repository=EmptyAiAnalysisRepository(),
        system_state_repository=EmptySystemStateRepository(),
    )
    candle = Candle(
        timestamp=utc_now(),
        open=100,
        high=110,
        low=95,
        close=108,
        volume=12,
    )
    local_market = MarketOverview(
        symbol="BTC/USDT",
        timeframe="1h",
        exchange=ExchangeId.BINANCE,
        last_price=1,
        change_24h_percent=0,
        volume_24h=1,
        volatility=0,
        rsi=50,
        data_latency_seconds=0,
        data_integrity="local_cache",
        candles=[candle],
    )

    class FakeMarketClient:
        def get_market_data(self, symbol: str, timeframe: str, limit: int) -> MarketDataSnapshot:
            return MarketDataSnapshot(
                exchange=ExchangeId.BINANCE,
                symbol=symbol,
                timeframe=timeframe,
                ticker=MarketTicker(
                    symbol=symbol,
                    last_price=108,
                    change_24h_percent=2.5,
                    volume_24h=1234,
                    received_at=utc_now(),
                ),
                candles=[candle],
            )

    monkeypatch.setattr(service, "_get_local_market_overview", lambda *args: local_market)
    monkeypatch.setattr(service, "_get_market_cache", lambda *args: None)
    monkeypatch.setattr(service, "_cache_public_market_candles", lambda **_kwargs: None)
    monkeypatch.setattr(
        "app.application.workbench.get_spot_market_client",
        lambda *args, **kwargs: FakeMarketClient(),
    )

    overview = service.get_market_overview()

    assert overview.data_integrity == "live_public"
    assert overview.last_price == 108


def test_public_market_candles_are_cached_for_future_analysis(monkeypatch) -> None:
    service = WorkbenchApplicationService(
        settings=Settings(_env_file=None, REPOSITORY_BACKEND="mysql"),
        portfolio_repository=EmptyPortfolioRepository(),
        strategy_repository=EmptyStrategyRepository(),
        audit_log_repository=EmptyAuditLogRepository(),
        risk_repository=EmptyRiskRepository(),
        ai_analysis_repository=EmptyAiAnalysisRepository(),
        system_state_repository=EmptySystemStateRepository(),
    )
    first_timestamp = datetime(2026, 6, 7, 8, tzinfo=timezone.utc)
    second_timestamp = datetime(2026, 6, 7, 9, tzinfo=timezone.utc)
    existing = MarketCandleRecord(
        exchange="binance",
        symbol="BTC/USDT",
        timeframe="1h",
        timestamp=first_timestamp,
        open=1,
        high=1,
        low=1,
        close=1,
        volume=1,
    )

    class FakeScalars:
        def all(self) -> list[MarketCandleRecord]:
            return [existing]

    class FakeSession:
        def __init__(self) -> None:
            self.added: list[MarketCandleRecord] = []
            self.committed = False
            self.closed = False

        def scalars(self, _query) -> FakeScalars:
            return FakeScalars()

        def add_all(self, records: list[MarketCandleRecord]) -> None:
            self.added.extend(records)

        def commit(self) -> None:
            self.committed = True

        def rollback(self) -> None:
            raise AssertionError("rollback should not be called")

        def close(self) -> None:
            self.closed = True

    fake_session = FakeSession()

    def fake_session_factory() -> FakeSession:
        return fake_session

    monkeypatch.setattr(
        "app.infrastructure.persistence.session.create_mysql_session_factory",
        lambda _settings: fake_session_factory,
    )

    service._cache_public_market_candles(
        exchange=ExchangeId.BINANCE,
        symbol="BTC/USDT",
        timeframe="1h",
        candles=[
            Candle(
                timestamp=first_timestamp,
                open=10,
                high=12,
                low=9,
                close=11,
                volume=100,
            ),
            Candle(
                timestamp=second_timestamp,
                open=11,
                high=13,
                low=10,
                close=12,
                volume=120,
            ),
        ],
    )

    assert existing.close == 11
    assert existing.volume == 100
    assert len(fake_session.added) == 1
    assert fake_session.added[0].timestamp == second_timestamp.replace(tzinfo=None)
    assert fake_session.added[0].close == 12
    assert fake_session.committed is True
    assert fake_session.closed is True


def test_historical_sync_requires_mysql_repository() -> None:
    result = make_service().sync_historical_market_data(HistoricalDataSyncRequest())

    assert result.status == "repository_unavailable"
    assert result.fetched == 0


def test_historical_sync_supports_okx(monkeypatch) -> None:
    service = WorkbenchApplicationService(
        settings=Settings(_env_file=None, REPOSITORY_BACKEND="mysql"),
        portfolio_repository=EmptyPortfolioRepository(),
        strategy_repository=EmptyStrategyRepository(),
        audit_log_repository=EmptyAuditLogRepository(),
        risk_repository=EmptyRiskRepository(),
        ai_analysis_repository=EmptyAiAnalysisRepository(),
        system_state_repository=EmptySystemStateRepository(),
    )
    candle = Candle(
        timestamp=datetime(2026, 1, 1, tzinfo=timezone.utc),
        open=100,
        high=110,
        low=90,
        close=105,
        volume=42,
    )
    seen: dict[str, object] = {}

    def fake_fetch_historical_candles(
        exchange: ExchangeId,
        symbol: str,
        timeframe: str,
        start_at: datetime,
        end_at: datetime,
    ) -> list[Candle]:
        seen.update(
            {
                "exchange": exchange,
                "symbol": symbol,
                "timeframe": timeframe,
                "start_at": start_at,
                "end_at": end_at,
            },
        )
        return [candle]

    monkeypatch.setattr(service, "_get_local_market_candles", lambda **_kwargs: [])
    monkeypatch.setattr(service, "_fetch_historical_candles", fake_fetch_historical_candles)
    class FakeWriteResult:
        inserted = 1
        updated = 0

    monkeypatch.setattr(
        service,
        "_cache_public_market_candles",
        lambda **_kwargs: FakeWriteResult(),
    )

    result = service.sync_historical_market_data(
        HistoricalDataSyncRequest(exchange=ExchangeId.OKX),
    )

    assert result.status == "completed"
    assert result.fetched == 1
    assert result.inserted == 1
    assert seen["exchange"] == ExchangeId.OKX
