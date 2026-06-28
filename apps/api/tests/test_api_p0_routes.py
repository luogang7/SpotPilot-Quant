from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import OperationalError

from app.api.v1.dependencies import get_workbench_service
from app.application.ai import AiServiceUnavailable
from app.application.workbench import WorkbenchApplicationService
from app.core.config import Settings
from app.domain.models import (
    AiAnalysis,
    AllowedDirection,
    BacktestRequest,
    BacktestResult,
    DailyPushSettingsUpdateRequest,
    ExchangeAccountConnectionTestRequest,
    ExchangeAccountConnectionTestResult,
    ExchangeAccountSettingsUpdateRequest,
    ExchangeId,
    HistoricalDataSyncRequest,
    HistoricalDataSyncResult,
    MarketOverview,
    NewsSentimentSummary,
    Order,
    RiskLevel,
    SentimentLabel,
    SettingsSummary,
    utc_now,
)
from app.infrastructure.repositories.memory import (
    EmptyAiAnalysisRepository,
    EmptyAuditLogRepository,
    EmptyPortfolioRepository,
    EmptyRiskRepository,
    EmptyStrategyRepository,
    EmptySystemStateRepository,
)
from app.main import app


client = TestClient(app)


@pytest.fixture(autouse=True)
def use_memory_workbench() -> None:
    service = WorkbenchApplicationService(
        settings=Settings(_env_file=None, ENABLE_PUBLIC_EXCHANGE_DATA=False, REPOSITORY_BACKEND="memory"),
        portfolio_repository=EmptyPortfolioRepository(),
        strategy_repository=EmptyStrategyRepository(),
        audit_log_repository=EmptyAuditLogRepository(),
        risk_repository=EmptyRiskRepository(),
        ai_analysis_repository=EmptyAiAnalysisRepository(),
        system_state_repository=EmptySystemStateRepository(),
    )

    def override_service() -> WorkbenchApplicationService:
        return service

    app.dependency_overrides[get_workbench_service] = override_service
    yield
    app.dependency_overrides.pop(get_workbench_service, None)


def test_strategy_update_route_persists_memory_backend_config() -> None:
    response = client.put(
        "/api/v1/strategies/ma_cross",
        json={"enabled": True, "parameters": {"fast_window": 6, "slow_window": 18}},
    )

    assert response.status_code == 200
    assert response.json()["parameters"] == {"fast_window": 6, "slow_window": 18}

    list_response = client.get("/api/v1/strategies")
    ma_cross = next(item for item in list_response.json() if item["id"] == "ma_cross")
    assert ma_cross["parameters"] == {"fast_window": 6, "slow_window": 18}


def test_api_routes_disable_conditional_http_cache() -> None:
    response = client.get("/api/v1/health", headers={"If-None-Match": '"cached-api-response"'})

    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    assert response.headers["cache-control"] == "no-store, no-cache, must-revalidate, max-age=0"
    assert response.headers["pragma"] == "no-cache"
    assert response.headers["expires"] == "0"
    assert "etag" not in response.headers
    assert "last-modified" not in response.headers


def test_database_errors_return_clear_503_response() -> None:
    class StubWorkbenchService:
        def get_system_status(self, probe: bool = True) -> None:
            raise OperationalError("SELECT 1", {}, RuntimeError("mysql unavailable"))

    def override_service() -> StubWorkbenchService:
        return StubWorkbenchService()

    app.dependency_overrides[get_workbench_service] = override_service
    try:
        response = client.get("/api/v1/system/status")
    finally:
        app.dependency_overrides.pop(get_workbench_service, None)

    assert response.status_code == 503
    assert "数据库连接不可用" in response.json()["detail"]
    assert response.headers["cache-control"] == "no-store, no-cache, must-revalidate, max-age=0"


def test_ai_validation_route_returns_high_risk_for_invalid_payload() -> None:
    response = client.post("/api/v1/ai-analysis/validate", json={"risk_level": "low"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["market_regime"] == "invalid_payload"
    assert payload["risk_level"] == "high"
    assert payload["allowed_direction"] == "none"


def test_ai_analysis_route_returns_503_when_ai_proxy_fails() -> None:
    class StubWorkbenchService:
        def get_ai_analysis(
            self,
            scope: str = "symbol",
            symbol: str | None = None,
            exchange: ExchangeId | None = None,
            refresh: bool = False,
            prefer_cached_snapshot: bool = False,
        ) -> None:
            raise AiServiceUnavailable("right code AI call failed: timed out")

    def override_service() -> StubWorkbenchService:
        return StubWorkbenchService()

    app.dependency_overrides[get_workbench_service] = override_service
    response = client.get("/api/v1/ai-analysis/latest")

    assert response.status_code == 503
    assert response.json()["detail"] == "right code AI call failed: timed out"


def test_ai_analysis_route_passes_requested_context() -> None:
    seen: dict[str, object] = {}

    class StubWorkbenchService:
        def get_ai_analysis(
            self,
            scope: str = "symbol",
            symbol: str | None = None,
            exchange: ExchangeId | None = None,
            refresh: bool = False,
            prefer_cached_snapshot: bool = False,
        ) -> AiAnalysis:
            seen.update({
                "scope": scope,
                "symbol": symbol,
                "exchange": exchange,
                "refresh": refresh,
                "prefer_cached_snapshot": prefer_cached_snapshot,
            })
            return AiAnalysis(
                analysis_scope=scope,
                symbol=symbol,
                market_regime="news_positive",
                sentiment_score=0.3,
                risk_level=RiskLevel.LOW,
                event_risk=False,
                allowed_direction=AllowedDirection.LONG_ONLY,
                confidence=0.7,
                provider="local_ai_mock",
                model="schema-validator",
                rationale=[],
                structured_payload={"symbol": symbol, "analysis_scope": scope},
            )

    def override_service() -> StubWorkbenchService:
        return StubWorkbenchService()

    app.dependency_overrides[get_workbench_service] = override_service
    try:
        response = client.get("/api/v1/ai-analysis/latest?scope=symbol&symbol=ARB%2FUSDT&exchange=okx&refresh=true")
    finally:
        app.dependency_overrides.pop(get_workbench_service, None)

    assert response.status_code == 200
    assert response.json()["symbol"] == "ARB/USDT"
    assert response.json()["analysis_scope"] == "symbol"
    assert "decision_signal" in response.json()
    assert seen == {
        "scope": "symbol",
        "symbol": "ARB/USDT",
        "exchange": ExchangeId.OKX,
        "refresh": True,
        "prefer_cached_snapshot": False,
    }


def test_ai_analysis_route_passes_market_scope_without_symbol() -> None:
    seen: dict[str, object] = {}

    class StubWorkbenchService:
        def get_ai_analysis(
            self,
            scope: str = "symbol",
            symbol: str | None = None,
            exchange: ExchangeId | None = None,
            refresh: bool = False,
            prefer_cached_snapshot: bool = False,
        ) -> AiAnalysis:
            seen.update({
                "scope": scope,
                "symbol": symbol,
                "exchange": exchange,
                "refresh": refresh,
                "prefer_cached_snapshot": prefer_cached_snapshot,
            })
            return AiAnalysis(
                analysis_scope=scope,
                symbol="MARKET",
                market_regime="market_news_neutral",
                sentiment_score=0,
                risk_level=RiskLevel.LOW,
                event_risk=False,
                allowed_direction=AllowedDirection.BOTH,
                confidence=0.65,
                provider="local_ai_mock",
                model="schema-validator",
                rationale=[],
                structured_payload={"symbol": "MARKET", "analysis_scope": scope},
            )

    def override_service() -> StubWorkbenchService:
        return StubWorkbenchService()

    app.dependency_overrides[get_workbench_service] = override_service
    try:
        response = client.get("/api/v1/ai-analysis/latest?scope=market&refresh=true")
    finally:
        app.dependency_overrides.pop(get_workbench_service, None)

    assert response.status_code == 200
    assert response.json()["symbol"] == "MARKET"
    assert response.json()["analysis_scope"] == "market"
    assert "decision_signal" in response.json()
    assert seen == {
        "scope": "market",
        "symbol": None,
        "exchange": None,
        "refresh": True,
        "prefer_cached_snapshot": False,
    }


def test_ai_analysis_route_passes_fast_cache_preference() -> None:
    seen: dict[str, object] = {}

    class StubWorkbenchService:
        def get_ai_analysis(
            self,
            scope: str = "symbol",
            symbol: str | None = None,
            exchange: ExchangeId | None = None,
            refresh: bool = False,
            prefer_cached_snapshot: bool = False,
        ) -> AiAnalysis:
            seen.update({
                "scope": scope,
                "symbol": symbol,
                "exchange": exchange,
                "refresh": refresh,
                "prefer_cached_snapshot": prefer_cached_snapshot,
            })
            return AiAnalysis(
                analysis_scope=scope,
                symbol=symbol,
                market_regime="cached_snapshot",
                sentiment_score=0,
                risk_level=RiskLevel.HIGH,
                event_risk=True,
                allowed_direction=AllowedDirection.NONE,
                confidence=0,
                provider="local_dashboard_fallback",
                model="snapshot-unavailable",
                rationale=[],
                structured_payload={},
            )

    def override_service() -> StubWorkbenchService:
        return StubWorkbenchService()

    app.dependency_overrides[get_workbench_service] = override_service
    try:
        response = client.get("/api/v1/ai-analysis/latest?scope=symbol&symbol=BTC%2FUSDT&fast=true")
    finally:
        app.dependency_overrides.pop(get_workbench_service, None)

    assert response.status_code == 200
    assert seen == {
        "scope": "symbol",
        "symbol": "BTC/USDT",
        "exchange": None,
        "refresh": False,
        "prefer_cached_snapshot": True,
    }


def test_news_sentiment_route_passes_requested_context() -> None:
    seen: dict[str, object] = {}

    class StubWorkbenchService:
        def get_news_sentiment(
            self,
            symbol: str | None = None,
            limit: int | None = None,
            refresh: bool = False,
        ) -> NewsSentimentSummary:
            seen.update({"symbol": symbol, "limit": limit, "refresh": refresh})
            return NewsSentimentSummary(
                symbol=symbol or "BTC/USDT",
                sentiment_score=0.25,
                sentiment_label=SentimentLabel.POSITIVE,
                risk_level=RiskLevel.LOW,
                status="ok",
                article_count=1,
                source_count=1,
            )

    def override_service() -> StubWorkbenchService:
        return StubWorkbenchService()

    app.dependency_overrides[get_workbench_service] = override_service
    try:
        response = client.get("/api/v1/ai-analysis/news?symbol=ETH%2FUSDT&limit=7&refresh=true")
    finally:
        app.dependency_overrides.pop(get_workbench_service, None)

    assert response.status_code == 200
    assert response.json()["symbol"] == "ETH/USDT"
    assert response.json()["sentiment_label"] == "positive"
    assert seen == {"symbol": "ETH/USDT", "limit": 7, "refresh": True}


def test_update_ai_proxy_settings_route_delegates_to_workbench_service() -> None:
    seen: dict[str, object] = {}

    class StubWorkbenchService:
        def update_ai_proxy_settings(self, request) -> SettingsSummary:
            seen.update(request.model_dump())
            return SettingsSummary(
                exchanges=[],
                ai_proxies=[
                    {
                        "id": "minimax",
                        "model": "MiniMax-M2.7",
                        "priority": 1,
                        "enabled": True,
                    },
                ],
                ai_provider_templates=[],
                data={},
                news_feeds=[],
                notifications={},
                safety_checks=[],
            )

    def override_service() -> StubWorkbenchService:
        return StubWorkbenchService()

    app.dependency_overrides[get_workbench_service] = override_service
    try:
        response = client.put(
            "/api/v1/settings/ai-proxies",
            json={
                "proxies": [
                    {
                        "slot": "A",
                        "provider": "minimax",
                        "base_url": "https://api.minimax.io/v1",
                        "api_key": "sk-test",
                        "model": "MiniMax-M2.7",
                        "priority": 1,
                        "enabled": True,
                        "api_format": "chat_completions",
                    },
                ],
            },
        )
    finally:
        app.dependency_overrides.pop(get_workbench_service, None)

    assert response.status_code == 200
    assert response.json()["ai_proxies"][0]["id"] == "minimax"
    assert seen["proxies"][0]["provider"] == "minimax"


def test_ai_proxy_connection_test_route_delegates_to_workbench_service() -> None:
    seen: dict[str, object] = {}

    class StubWorkbenchService:
        def test_ai_proxy_connection(self, request):
            seen.update(request.model_dump())
            return {
                "success": True,
                "provider": "minimax",
                "model": "MiniMax-M2.7",
                "message": "模型连通性正常，已返回有效结构化 JSON。",
                "latency_ms": 123,
                "used_saved_api_key": False,
            }

    def override_service() -> StubWorkbenchService:
        return StubWorkbenchService()

    app.dependency_overrides[get_workbench_service] = override_service
    try:
        response = client.post(
            "/api/v1/settings/ai-proxies/test",
            json={
                "proxy": {
                    "slot": "A",
                    "provider": "minimax",
                    "base_url": "https://api.minimax.io/v1",
                    "api_key": "sk-test",
                    "model": "MiniMax-M2.7",
                    "priority": 1,
                    "enabled": True,
                    "api_format": "chat_completions",
                },
                "timeout_seconds": 12,
            },
        )
    finally:
        app.dependency_overrides.pop(get_workbench_service, None)

    assert response.status_code == 200
    assert response.json()["success"] is True
    assert response.json()["latency_ms"] == 123
    assert seen["proxy"]["provider"] == "minimax"
    assert seen["timeout_seconds"] == 12


def test_update_exchange_account_settings_route_delegates_to_workbench_service() -> None:
    seen: dict[str, object] = {}

    class StubWorkbenchService:
        def update_exchange_account_settings(self, request: ExchangeAccountSettingsUpdateRequest) -> SettingsSummary:
            seen.update(request.model_dump())
            return SettingsSummary(
                exchanges=[
                    {
                        "id": "okx",
                        "api_key_configured": True,
                        "spot_trading_enabled": True,
                        "sandbox": False,
                    },
                ],
                ai_proxies=[],
                ai_provider_templates=[],
                data={},
                news_feeds=[],
                notifications={},
                safety_checks=[],
            )

    def override_service() -> StubWorkbenchService:
        return StubWorkbenchService()

    app.dependency_overrides[get_workbench_service] = override_service
    try:
        response = client.put(
            "/api/v1/settings/exchange-accounts",
            json={
                "accounts": [
                    {
                        "exchange": "okx",
                        "api_key": "okx-key",
                        "api_secret": "okx-secret",
                        "passphrase": "okx-passphrase",
                        "spot_trading_enabled": True,
                        "sandbox": False,
                    },
                ],
            },
        )
    finally:
        app.dependency_overrides.pop(get_workbench_service, None)

    assert response.status_code == 200
    assert response.json()["exchanges"][0]["id"] == "okx"
    assert seen["accounts"][0]["exchange"] == ExchangeId.OKX
    assert seen["accounts"][0]["spot_trading_enabled"] is True


def test_exchange_account_connection_test_route_delegates_to_workbench_service() -> None:
    seen: dict[str, object] = {}

    class StubWorkbenchService:
        def test_exchange_account_connection(
            self,
            request: ExchangeAccountConnectionTestRequest,
        ) -> ExchangeAccountConnectionTestResult:
            seen.update(request.model_dump())
            return ExchangeAccountConnectionTestResult(
                success=True,
                exchange=ExchangeId.OKX,
                message="交易所账号连通性正常，已完成只读余额校验。",
                latency_ms=88,
                used_saved_credentials=False,
                balance_asset_count=2,
            )

    def override_service() -> StubWorkbenchService:
        return StubWorkbenchService()

    app.dependency_overrides[get_workbench_service] = override_service
    try:
        response = client.post(
            "/api/v1/settings/exchange-accounts/test",
            json={
                "account": {
                    "exchange": "okx",
                    "api_key": "okx-key",
                    "api_secret": "okx-secret",
                    "passphrase": "okx-passphrase",
                    "spot_trading_enabled": True,
                    "sandbox": False,
                },
                "timeout_seconds": 12,
            },
        )
    finally:
        app.dependency_overrides.pop(get_workbench_service, None)

    assert response.status_code == 200
    assert response.json()["success"] is True
    assert response.json()["exchange"] == "okx"
    assert response.json()["balance_asset_count"] == 2
    assert seen["account"]["exchange"] == ExchangeId.OKX
    assert seen["timeout_seconds"] == 12


def test_update_notification_settings_route_delegates_to_workbench_service() -> None:
    seen: dict[str, object] = {}

    class StubWorkbenchService:
        def update_notification_settings(self, request) -> SettingsSummary:
            seen.update(request.model_dump())
            return SettingsSummary(
                exchanges=[],
                ai_proxies=[],
                ai_provider_templates=[],
                data={},
                news_feeds=[],
                notifications={
                    "wecom_webhook": True,
                    "telegram_bot": True,
                    "email_smtp": False,
                    "slack_webhook": False,
                    "discord_webhook": False,
                    "feishu_webhook": False,
                },
                safety_checks=[],
            )

    def override_service() -> StubWorkbenchService:
        return StubWorkbenchService()

    app.dependency_overrides[get_workbench_service] = override_service
    try:
        response = client.put(
            "/api/v1/settings/notifications",
            json={
                "channels": [
                    {
                        "provider": "wecom",
                        "webhook_url": "https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=test",
                    },
                    {
                        "provider": "telegram",
                        "telegram_bot_token": "token",
                        "telegram_chat_id": "chat",
                    },
                ],
            },
        )
    finally:
        app.dependency_overrides.pop(get_workbench_service, None)

    assert response.status_code == 200
    assert response.json()["notifications"]["wecom_webhook"] is True
    assert seen["channels"][0]["provider"] == "wecom"
    assert seen["channels"][0]["webhook_url"].startswith("https://qyapi.weixin.qq.com")
    assert seen["channels"][1]["telegram_chat_id"] == "chat"


def test_update_daily_push_settings_route_delegates_to_workbench_service() -> None:
    seen: dict[str, object] = {}

    class StubWorkbenchService:
        def update_daily_push_settings(self, request: DailyPushSettingsUpdateRequest) -> SettingsSummary:
            seen["payload"] = request.model_dump()
            return SettingsSummary(
                exchanges=[],
                ai_proxies=[],
                ai_provider_templates=[],
                data={
                    "schedule_enabled": "true",
                    "schedule_time": "09:30",
                    "schedule_times": "09:30,18:00",
                    "schedule_run_immediately": "false",
                },
                news_feeds=[],
                notifications={},
                safety_checks=[],
            )

    def override_service() -> StubWorkbenchService:
        return StubWorkbenchService()

    app.dependency_overrides[get_workbench_service] = override_service
    try:
        response = client.put(
            "/api/v1/settings/daily-push",
            json={
                "enabled": True,
                "schedule_time": "09:30",
                "schedule_times": "09:30,18:00",
                "run_immediately": False,
            },
        )
    finally:
        app.dependency_overrides.pop(get_workbench_service, None)

    assert response.status_code == 200
    assert response.json()["data"]["schedule_enabled"] == "true"
    assert seen["payload"] == {
        "enabled": True,
        "schedule_time": "09:30",
        "schedule_times": "09:30,18:00",
        "run_immediately": False,
    }


def test_dry_run_order_route_does_not_fabricate_account_execution() -> None:
    response = client.post(
        "/api/v1/trading/dry-run/orders",
        json={"symbol": "BTC/USDT", "action": "buy", "quantity": 0.01},
    )

    assert response.status_code == 200
    assert response.json()["status"].startswith("rejected_by_risk:")

    summary = client.get("/api/v1/trading/summary").json()
    assert summary["balances"] == []
    assert summary["positions"] == []
    assert len(summary["historical_orders"]) >= 1


def test_live_trading_routes_delegate_to_workbench_service() -> None:
    seen: list[str] = []

    class StubWorkbenchService:
        @staticmethod
        def _order(order_id: str, side: str, status: str = "open") -> Order:
            return Order(
                order_id=order_id,
                exchange=ExchangeId.BINANCE,
                symbol="BTC/USDT",
                side=side,
                order_type="market",
                price=0,
                quantity=0.01,
                status=status,
                created_at=utc_now(),
            )

        def create_live_order(self, request) -> Order:
            seen.append(f"create:{request.exchange.value}:{request.symbol}:{request.action.value}")
            return self._order("LIVE-1", "buy")

        def cancel_live_order(self, request) -> Order:
            seen.append(f"cancel:{request.exchange.value}:{request.symbol}:{request.order_id}")
            return self._order(request.order_id, "cancel_order", "canceled")

        def close_live_position(self, request) -> Order:
            seen.append(f"close:{request.exchange.value}:{request.symbol}:{request.quantity}")
            return self._order("CLOSE-1", "sell", "closed")

    def override_service() -> StubWorkbenchService:
        return StubWorkbenchService()

    app.dependency_overrides[get_workbench_service] = override_service
    try:
        create_response = client.post(
            "/api/v1/trading/live/orders",
            json={"exchange": "binance", "symbol": "BTC/USDT", "action": "buy", "quantity": 0.01},
        )
        cancel_response = client.post(
            "/api/v1/trading/live/orders/cancel",
            json={"exchange": "binance", "symbol": "BTC/USDT", "order_id": "LIVE-1"},
        )
        close_response = client.post(
            "/api/v1/trading/live/positions/close",
            json={"exchange": "binance", "symbol": "BTC/USDT", "quantity": 0.01},
        )
    finally:
        app.dependency_overrides.pop(get_workbench_service, None)

    assert create_response.status_code == 200
    assert create_response.json()["order_id"] == "LIVE-1"
    assert cancel_response.status_code == 200
    assert cancel_response.json()["status"] == "canceled"
    assert close_response.status_code == 200
    assert close_response.json()["side"] == "sell"
    assert seen == [
        "create:binance:BTC/USDT:buy",
        "cancel:binance:BTC/USDT:LIVE-1",
        "close:binance:BTC/USDT:0.01",
    ]


def test_trade_trace_route_returns_strategy_ai_risk_order_chain() -> None:
    order_response = client.post(
        "/api/v1/trading/dry-run/orders",
        json={"symbol": "BTC/USDT", "action": "buy", "quantity": 0.01, "strategy": "ma_cross"},
    )
    correlation_id = order_response.json()["correlation_id"]

    trace_response = client.get(f"/api/v1/trading/traces/{correlation_id}")

    assert trace_response.status_code == 200
    payload = trace_response.json()
    assert payload["correlation_id"] == correlation_id
    assert payload["signal"]["strategy"] == "ma_cross"
    assert payload["ai_analysis"]["correlation_id"] == correlation_id
    assert payload["order"]["correlation_id"] == correlation_id
    assert {log["module"] for log in payload["logs"]} >= {"strategy", "ai", "risk", "trading"}


def test_system_control_pause_is_persisted_by_backend() -> None:
    update_response = client.put(
        "/api/v1/system/control",
        json={"paused": True, "reason": "test_pause"},
    )

    assert update_response.status_code == 200
    assert update_response.json()["paused"] is True

    status_response = client.get("/api/v1/system/status")

    assert status_response.status_code == 200
    assert status_response.json()["paused"] is True


def test_kill_switch_blocks_dry_run_opening_through_risk() -> None:
    client.put(
        "/api/v1/system/control",
        json={"paused": True, "kill_switch_armed": True, "reason": "test_kill_switch"},
    )

    order_response = client.post(
        "/api/v1/trading/dry-run/orders",
        json={"symbol": "BTC/USDT", "action": "buy", "quantity": 0.01},
    )

    assert order_response.status_code == 200
    assert order_response.json()["status"] == "rejected_by_risk:paused"


def test_notification_test_route_is_explicit_when_webhook_is_missing() -> None:
    response = client.post("/api/v1/settings/notifications/test", json={"message": "test"})

    assert response.status_code == 200
    assert response.json()["success"] is False
    assert "not configured" in response.json()["message"]


def test_daily_push_route_returns_explicit_result_when_channels_missing() -> None:
    response = client.post("/api/v1/settings/notifications/daily-push/run")

    assert response.status_code == 200
    assert response.json()["success"] is False
    assert response.json()["results"][0]["provider"] == "all"
    assert "🎯 今日结论" in response.json()["message"]


def test_market_overview_route_passes_requested_candle_limit() -> None:
    seen: dict[str, object] = {}

    class StubWorkbenchService:
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
            seen.update({
                "symbol": symbol,
                "timeframe": timeframe,
                "exchange": exchange,
                "limit": limit,
                "before": before,
                "prefer_live": prefer_live,
                "refresh": refresh,
                "allow_stale_local": allow_stale_local,
            })
            return MarketOverview(
                symbol=symbol or "BTC/USDT",
                timeframe=timeframe or "1h",
                exchange=exchange or ExchangeId.BINANCE,
                last_price=0,
                change_24h_percent=0,
                volume_24h=0,
                volatility=0,
                rsi=0,
                data_latency_seconds=0,
                data_integrity="test",
                candles=[],
            )

    def override_service() -> StubWorkbenchService:
        return StubWorkbenchService()

    app.dependency_overrides[get_workbench_service] = override_service
    try:
        response = client.get("/api/v1/market/overview?symbol=ETH%2FUSDT&timeframe=4h&exchange=okx&limit=750")
    finally:
        app.dependency_overrides.pop(get_workbench_service, None)

    assert response.status_code == 200
    assert seen == {
        "symbol": "ETH/USDT",
        "timeframe": "4h",
        "exchange": ExchangeId.OKX,
        "limit": 750,
        "before": None,
        "prefer_live": True,
        "refresh": False,
        "allow_stale_local": False,
    }


def test_market_overview_route_passes_fast_cache_preference() -> None:
    seen: dict[str, object] = {}

    class StubWorkbenchService:
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
            seen.update({
                "symbol": symbol,
                "timeframe": timeframe,
                "exchange": exchange,
                "limit": limit,
                "before": before,
                "prefer_live": prefer_live,
                "refresh": refresh,
                "allow_stale_local": allow_stale_local,
            })
            return MarketOverview(
                symbol=symbol or "BTC/USDT",
                timeframe=timeframe or "1h",
                exchange=exchange or ExchangeId.BINANCE,
                last_price=0,
                change_24h_percent=0,
                volume_24h=0,
                volatility=0,
                rsi=0,
                data_latency_seconds=0,
                data_integrity="local_cache_empty",
                candles=[],
            )

    def override_service() -> StubWorkbenchService:
        return StubWorkbenchService()

    app.dependency_overrides[get_workbench_service] = override_service
    try:
        response = client.get("/api/v1/market/overview?symbol=BTC%2FUSDT&fast=true")
    finally:
        app.dependency_overrides.pop(get_workbench_service, None)

    assert response.status_code == 200
    assert seen == {
        "symbol": "BTC/USDT",
        "timeframe": None,
        "exchange": None,
        "limit": 500,
        "before": None,
        "prefer_live": False,
        "refresh": False,
        "allow_stale_local": True,
    }


def test_market_overview_route_passes_before_cursor() -> None:
    seen: dict[str, object] = {}

    class StubWorkbenchService:
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
            seen.update({
                "symbol": symbol,
                "timeframe": timeframe,
                "exchange": exchange,
                "limit": limit,
                "before": before,
                "prefer_live": prefer_live,
                "refresh": refresh,
                "allow_stale_local": allow_stale_local,
            })
            return MarketOverview(
                symbol=symbol or "BTC/USDT",
                timeframe=timeframe or "1h",
                exchange=exchange or ExchangeId.BINANCE,
                last_price=0,
                change_24h_percent=0,
                volume_24h=0,
                volatility=0,
                rsi=0,
                data_latency_seconds=0,
                data_integrity="local_cache",
                candles=[],
            )

    def override_service() -> StubWorkbenchService:
        return StubWorkbenchService()

    app.dependency_overrides[get_workbench_service] = override_service
    try:
        response = client.get(
            "/api/v1/market/overview?symbol=BTC%2FUSDT&before=2026-06-28T08%3A00%3A00Z&fast=true",
        )
    finally:
        app.dependency_overrides.pop(get_workbench_service, None)

    assert response.status_code == 200
    assert seen["before"] == datetime(2026, 6, 28, 8, tzinfo=timezone.utc)
    assert seen["prefer_live"] is False
    assert seen["allow_stale_local"] is True


def test_historical_sync_route_passes_requested_range() -> None:
    seen: dict[str, object] = {}

    class StubWorkbenchService:
        def sync_historical_market_data(
            self,
            request: HistoricalDataSyncRequest,
        ) -> HistoricalDataSyncResult:
            seen.update(request.model_dump())
            return HistoricalDataSyncResult(
                symbol=request.symbol,
                exchange=request.exchange,
                timeframe=request.timeframe,
                start_date=request.start_date,
                end_date=request.end_date,
                fetched=10,
                inserted=8,
                updated=2,
            )

    def override_service() -> StubWorkbenchService:
        return StubWorkbenchService()

    app.dependency_overrides[get_workbench_service] = override_service
    try:
        response = client.post(
            "/api/v1/market/history/sync",
            json={
                "symbol": "ETH/USDT",
                "exchange": "binance",
                "timeframe": "1h",
                "start_date": "2026-01-01",
                "end_date": "2026-02-01",
            },
        )
    finally:
        app.dependency_overrides.pop(get_workbench_service, None)

    assert response.status_code == 200
    assert response.json()["fetched"] == 10
    assert seen["symbol"] == "ETH/USDT"
    assert seen["exchange"] == ExchangeId.BINANCE
    assert seen["start_date"] == "2026-01-01"
    assert seen["end_date"] == "2026-02-01"


def test_backtest_export_route_returns_requested_attachment() -> None:
    seen: dict[str, object] = {}

    class StubWorkbenchService:
        def run_backtest(self, request: BacktestRequest) -> BacktestResult:
            seen.update(request.model_dump())
            return BacktestResult(
                request=request,
                status="completed",
                message="stub",
                total_return_percent=1.2,
                annual_return_percent=2.3,
                max_drawdown_percent=0.4,
                win_rate_percent=100,
                profit_factor=12,
                trade_count=0,
                equity_curve=[request.initial_capital],
                trades=[],
            )

    def override_service() -> StubWorkbenchService:
        return StubWorkbenchService()

    app.dependency_overrides[get_workbench_service] = override_service
    try:
        response = client.post(
            "/api/v1/backtests/export?format=csv",
            json={"symbol": "ETH/USDT", "strategy_id": "breakout", "start_date": "2026-01-01", "end_date": "2026-02-01"},
        )
    finally:
        app.dependency_overrides.pop(get_workbench_service, None)

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/csv")
    assert "attachment;" in response.headers["content-disposition"]
    assert "strategy_id,breakout" in response.text
    assert "symbol,ETH/USDT" in response.text
    assert "trade_count,0" in response.text
    assert seen["strategy_id"] == "breakout"
