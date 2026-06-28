from app.core.safety import assert_spot_action
from app.domain.models import (
    DryRunOrderRequest,
    Order,
    Position,
    RiskStatus,
    RiskStatusResponse,
    SpotSignalAction,
    utc_now,
)


class DryRunTradingService:
    def validate_order(
        self,
        request: DryRunOrderRequest,
        positions: list[Position],
        risk: RiskStatusResponse | None = None,
    ) -> Order:
        assert_spot_action(request.action.value)
        if self._new_position_blocked(request, risk):
            return self._order(request, status=f"rejected_by_risk:{risk.status.value}")
        if request.action == SpotSignalAction.SELL_EXISTING:
            position = next((item for item in positions if item.symbol == request.symbol), None)
            if position is None or request.quantity > position.quantity:
                return self._order(request, status="rejected_no_spot_position")
        if request.action == SpotSignalAction.CANCEL_ORDER:
            return self._order(request, status="validated_cancel_only")
        if request.action == SpotSignalAction.HOLD:
            return self._order(request, status="validated_hold")
        return self._order(request, status="validated_dry_run")

    @staticmethod
    def _new_position_blocked(
        request: DryRunOrderRequest,
        risk: RiskStatusResponse | None,
    ) -> bool:
        return (
            request.action == SpotSignalAction.BUY
            and risk is not None
            and risk.status != RiskStatus.ALLOW_TRADING
        )

    @staticmethod
    def _order(request: DryRunOrderRequest, status: str) -> Order:
        return Order(
            order_id=f"DRY-{int(utc_now().timestamp() * 1000)}",
            symbol=request.symbol,
            side=request.action.value,
            order_type=request.order_type,
            price=request.price or 0,
            quantity=request.quantity,
            fee=0,
            status=status,
            created_at=utc_now(),
        )
