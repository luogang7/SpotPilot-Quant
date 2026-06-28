import pytest

from app.application.risk import RiskEngine
from app.application.trading import DryRunTradingService
from app.domain.models import (
    AiAnalysis,
    AllowedDirection,
    Balance,
    DryRunOrderRequest,
    Position,
    RiskLevel,
    SpotSignalAction,
)


def test_dry_run_buy_is_validated_without_exchange_order() -> None:
    order = DryRunTradingService().validate_order(
        DryRunOrderRequest(
            symbol="BTC/USDT",
            action=SpotSignalAction.BUY,
            quantity=0.01,
            price=50_000,
            strategy="ma_cross",
        ),
        positions=[],
    )

    assert order.status == "validated_dry_run"
    assert order.side == "buy"
    assert order.order_id.startswith("DRY-")


def test_dry_run_buy_is_rejected_when_risk_blocks_new_positions() -> None:
    risk = RiskEngine().evaluate(
        balances=[Balance(asset="USDT", free=1000, locked=0, total=1000)],
        positions=[],
        ai=AiAnalysis(
            market_regime="trend",
            sentiment_score=0,
            risk_level=RiskLevel.LOW,
            event_risk=False,
            allowed_direction=AllowedDirection.LONG_ONLY,
            confidence=0.8,
            provider="test",
            model="schema",
            rationale=[],
            structured_payload={},
        ),
        persisted_rules=[],
        data_latency_seconds=999,
        data_integrity="local_cache",
    )

    order = DryRunTradingService().validate_order(
        DryRunOrderRequest(symbol="BTC/USDT", action=SpotSignalAction.BUY, quantity=0.01),
        positions=[],
        risk=risk,
    )

    assert order.status == "rejected_by_risk:no_new_positions"


def test_dry_run_sell_rejects_missing_existing_spot_position() -> None:
    order = DryRunTradingService().validate_order(
        DryRunOrderRequest(symbol="BTC/USDT", action=SpotSignalAction.SELL_EXISTING, quantity=1),
        positions=[],
    )

    assert order.status == "rejected_no_spot_position"


def test_dry_run_sell_allows_existing_spot_position_quantity() -> None:
    order = DryRunTradingService().validate_order(
        DryRunOrderRequest(symbol="BTC/USDT", action=SpotSignalAction.SELL_EXISTING, quantity=0.5),
        positions=[
            Position(
                symbol="BTC/USDT",
                quantity=1,
                average_price=50_000,
                current_price=51_000,
                unrealized_pnl=1_000,
            ),
        ],
    )

    assert order.status == "validated_dry_run"


def test_order_request_rejects_unknown_actions_at_schema_boundary() -> None:
    with pytest.raises(ValueError):
        DryRunOrderRequest(symbol="BTC/USDT", action="short", quantity=1)
