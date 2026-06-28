import pytest

from app.application.ai import AiMockValidationService
import app.application.workbench as workbench_module
from app.application.workbench import WorkbenchApplicationService
from app.core.config import Settings
from app.domain.models import (
    AiAnalysis,
    AllowedDirection,
    ConnectionState,
    ExchangeId,
    ExchangeStatus,
    RiskLevel,
    utc_now,
)
from app.infrastructure.exchanges.base import ExchangeMarketDataError
from app.infrastructure.repositories.memory import (
    InMemoryAiAnalysisRepository,
    InMemoryAuditLogRepository,
    InMemoryPortfolioRepository,
    InMemoryRiskRepository,
    InMemoryStrategyRepository,
    InMemorySystemStateRepository,
)


def build_service(settings: Settings | None = None) -> WorkbenchApplicationService:
    return WorkbenchApplicationService(
        settings=settings or Settings(),
        portfolio_repository=InMemoryPortfolioRepository(),
        strategy_repository=InMemoryStrategyRepository(),
        audit_log_repository=InMemoryAuditLogRepository(),
        risk_repository=InMemoryRiskRepository(),
        ai_analysis_repository=InMemoryAiAnalysisRepository(),
        system_state_repository=InMemorySystemStateRepository(),
    )


def clear_runtime_caches() -> None:
    workbench_module._MARKET_OVERVIEW_CACHE.clear()
    workbench_module._EXTERNAL_FAILURE_COOLDOWNS.clear()
    workbench_module._AI_ANALYSIS_CACHE.clear()
    workbench_module._NEWS_SENTIMENT_CACHE.clear()
    workbench_module._SYSTEM_MARKET_STATUS_CACHE.clear()


def test_market_overview_cools_down_after_exchange_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    clear_runtime_caches()
    calls = 0

    class FailingMarketClient:
        def get_market_data(self, *args: object, **kwargs: object) -> object:
            nonlocal calls
            calls += 1
            raise ExchangeMarketDataError("network unavailable")

    monkeypatch.setattr(
        "app.application.workbench.get_spot_market_client",
        lambda *args, **kwargs: FailingMarketClient(),
    )

    service = build_service(
        Settings(
            REPOSITORY_BACKEND="memory",
            EXTERNAL_FAILURE_COOLDOWN_SECONDS=60,
            PUBLIC_MARKET_CACHE_TTL_SECONDS=60,
        ),
    )

    first = service.get_market_overview()
    second = service.get_market_overview()

    assert calls == 1
    assert first.data_integrity.startswith("exchange_error:")
    assert second.data_integrity == "exchange_error_cooling_down"


def test_dashboard_uses_fast_ai_snapshot_by_default() -> None:
    clear_runtime_caches()
    calls = 0
    validator = AiMockValidationService()

    class CountingAiService:
        provider = validator.provider
        model = validator.model

        def analyze_empty_context(self, *args: object, **kwargs: object):
            nonlocal calls
            calls += 1
            return validator.analyze_empty_context(*args, **kwargs)

    service = build_service(Settings(REPOSITORY_BACKEND="memory", AI_ANALYSIS_CACHE_TTL_SECONDS=60))
    service.ai_service = CountingAiService()

    service.get_dashboard()

    assert calls == 0


def test_dashboard_refresh_forces_ai_analysis_once() -> None:
    clear_runtime_caches()
    calls = 0
    validator = AiMockValidationService()

    class CountingAiService:
        provider = validator.provider
        model = validator.model

        def analyze_empty_context(self, *args: object, **kwargs: object):
            nonlocal calls
            calls += 1
            return validator.analyze_empty_context(*args, **kwargs)

    service = build_service(Settings(REPOSITORY_BACKEND="memory", AI_ANALYSIS_CACHE_TTL_SECONDS=60))
    service.ai_service = CountingAiService()

    service.get_dashboard(refresh=True)

    assert calls == 1


def test_fast_ai_analysis_fallback_matches_requested_market_scope() -> None:
    clear_runtime_caches()
    service = build_service(Settings(REPOSITORY_BACKEND="memory", ENABLE_PUBLIC_EXCHANGE_DATA=False))
    service.ai_analysis_repository.save_analysis(
        AiAnalysis(
            analysis_scope="symbol",
            symbol="BTC/USDT",
            market_regime="stable",
            sentiment_score=0,
            risk_level=RiskLevel.LOW,
            event_risk=False,
            allowed_direction=AllowedDirection.LONG_ONLY,
            confidence=0.8,
            provider="test",
            model="snapshot",
            rationale=[],
            structured_payload={"analysis_scope": "symbol", "symbol": "BTC/USDT"},
        ),
    )

    analysis = service.get_ai_analysis(scope="market", prefer_cached_snapshot=True)

    assert analysis.analysis_scope == "market"
    assert analysis.symbol == "MARKET"
    assert analysis.decision_signal is not None
    assert analysis.decision_signal.analysis_scope == "market"
    assert analysis.decision_signal.symbol == "MARKET"


def test_system_status_skips_public_exchange_probe_when_disabled() -> None:
    clear_runtime_caches()
    calls = 0
    service = build_service(
        Settings(
            REPOSITORY_BACKEND="memory",
            ENABLE_PUBLIC_EXCHANGE_DATA=True,
        ),
    )

    def probe(exchange: ExchangeId) -> tuple[ExchangeStatus, object]:
        nonlocal calls
        calls += 1
        return (
            ExchangeStatus(exchange=exchange, state=ConnectionState.HEALTHY, message="checked"),
            utc_now(),
        )

    service._probe_public_exchange_status = probe  # type: ignore[method-assign]

    status = service.get_system_status(probe=False)

    assert calls == 0
    assert status.data_latency_seconds is None
    assert all(exchange.state == ConnectionState.DEGRADED for exchange in status.exchanges)


def test_risk_status_uses_persisted_ai_snapshot_without_external_ai_call() -> None:
    clear_runtime_caches()

    class ExplodingAiService:
        provider = "test"
        model = "unreachable"

        def analyze_empty_context(self, *args: object, **kwargs: object) -> AiAnalysis:
            raise AssertionError("risk status must not call the external AI service")

    service = build_service(
        Settings(
            REPOSITORY_BACKEND="memory",
            ENABLE_PUBLIC_EXCHANGE_DATA=False,
        ),
    )
    service.ai_service = ExplodingAiService()
    service.ai_analysis_repository.save_analysis(
        AiAnalysis(
            analysis_scope="symbol",
            symbol="BTC/USDT",
            market_regime="stable",
            sentiment_score=0,
            risk_level=RiskLevel.LOW,
            event_risk=False,
            allowed_direction=AllowedDirection.LONG_ONLY,
            confidence=0.8,
            provider="test",
            model="snapshot",
            rationale=[],
            structured_payload={},
        ),
    )

    response = service.get_risk_status()

    ai_rule = next(rule for rule in response.rules if rule.name == "AI 高风险暂停")
    assert ai_rule.current_value == "low"


def test_risk_status_uses_local_market_snapshot_without_exchange_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clear_runtime_caches()

    def fail_exchange_client(*args: object, **kwargs: object) -> object:
        raise AssertionError("risk status must not call the live exchange client")

    monkeypatch.setattr("app.application.workbench.get_spot_market_client", fail_exchange_client)
    service = build_service(Settings(REPOSITORY_BACKEND="memory", ENABLE_PUBLIC_EXCHANGE_DATA=True))

    response = service.get_risk_status()

    data_rule = next(rule for rule in response.rules if rule.name == "数据延迟")
    assert data_rule.current_value == "0s / local_cache_empty"
