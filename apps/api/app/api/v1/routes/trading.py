from fastapi import APIRouter, Depends, HTTPException

from app.api.v1.dependencies import get_workbench_service
from app.application.workbench import WorkbenchApplicationService
from app.domain.models import (
    DryRunOrderRequest,
    LiveCancelOrderRequest,
    LiveOrderRequest,
    ManualClosePositionRequest,
    Order,
    TradeDecisionTrace,
    TradingSummary,
)

router = APIRouter()


@router.get("/summary", response_model=TradingSummary)
def get_trading_summary(
    service: WorkbenchApplicationService = Depends(get_workbench_service),
) -> TradingSummary:
    return service.get_trading_summary()


@router.post("/dry-run/orders", response_model=Order)
def create_dry_run_order(
    request: DryRunOrderRequest,
    service: WorkbenchApplicationService = Depends(get_workbench_service),
) -> Order:
    try:
        return service.create_dry_run_order(request)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/live/orders", response_model=Order)
def create_live_order(
    request: LiveOrderRequest,
    service: WorkbenchApplicationService = Depends(get_workbench_service),
) -> Order:
    try:
        return service.create_live_order(request)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/live/orders/cancel", response_model=Order)
def cancel_live_order(
    request: LiveCancelOrderRequest,
    service: WorkbenchApplicationService = Depends(get_workbench_service),
) -> Order:
    try:
        return service.cancel_live_order(request)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/live/positions/close", response_model=Order)
def close_live_position(
    request: ManualClosePositionRequest,
    service: WorkbenchApplicationService = Depends(get_workbench_service),
) -> Order:
    try:
        return service.close_live_position(request)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/traces/{correlation_id}", response_model=TradeDecisionTrace)
def get_trade_decision_trace(
    correlation_id: str,
    service: WorkbenchApplicationService = Depends(get_workbench_service),
) -> TradeDecisionTrace:
    trace = service.get_trade_decision_trace(correlation_id)
    if trace.order is None and trace.signal is None and trace.ai_analysis is None and not trace.logs:
        raise HTTPException(status_code=404, detail=f"Trace not found: {correlation_id}")
    return trace
