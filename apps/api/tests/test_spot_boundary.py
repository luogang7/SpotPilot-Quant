import pytest

from app.application.workbench import WorkbenchApplicationService
from app.core.config import Settings
from app.core.safety import DISALLOWED_SIGNAL_ACTIONS, SPOT_ALLOWED_ACTIONS, assert_spot_action
from app.domain.models import SpotSignalAction
from app.infrastructure.repositories.memory import (
    EmptyAiAnalysisRepository,
    EmptyAuditLogRepository,
    EmptyPortfolioRepository,
    EmptyRiskRepository,
    EmptyStrategyRepository,
    EmptySystemStateRepository,
)


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


def test_spot_signal_actions_do_not_include_short_or_leverage() -> None:
    declared_actions = {action.value for action in SpotSignalAction}

    assert declared_actions == SPOT_ALLOWED_ACTIONS
    assert declared_actions.isdisjoint(DISALLOWED_SIGNAL_ACTIONS)


def test_rejects_non_spot_action() -> None:
    with pytest.raises(ValueError):
        assert_spot_action("short")


def test_dashboard_is_empty_by_default() -> None:
    dashboard = make_service().get_dashboard()

    assert dashboard.positions == []
    assert dashboard.latest_signals == []
    assert dashboard.latest_logs == []
    assert dashboard.system.trading_mode.value == "dry_run"


def test_trading_summary_is_empty_without_private_api() -> None:
    summary = make_service().get_trading_summary()

    assert summary.balances == []
    assert summary.positions == []
    assert summary.open_orders == []
    assert summary.historical_orders == []
    assert summary.spot_only is True
    assert summary.contract_trading_disabled is True
