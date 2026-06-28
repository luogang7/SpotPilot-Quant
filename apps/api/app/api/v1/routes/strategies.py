from fastapi import APIRouter, Depends, HTTPException

from app.api.v1.dependencies import get_workbench_service
from app.application.workbench import WorkbenchApplicationService
from app.domain.models import ExchangeId, StrategyConfig, StrategySignal, StrategyUpdateRequest

router = APIRouter()


@router.get("", response_model=list[StrategyConfig])
def list_strategies(
    service: WorkbenchApplicationService = Depends(get_workbench_service),
) -> list[StrategyConfig]:
    return service.get_strategies()


@router.post("/signals/run", response_model=list[StrategySignal])
def run_strategy_signals(
    symbol: str | None = None,
    timeframe: str | None = None,
    exchange: ExchangeId | None = None,
    limit: int = 200,
    service: WorkbenchApplicationService = Depends(get_workbench_service),
) -> list[StrategySignal]:
    return service.generate_strategy_signals(
        symbol=symbol,
        timeframe=timeframe,
        exchange=exchange,
        limit=limit,
    )


@router.put("/{strategy_id}", response_model=StrategyConfig)
def update_strategy(
    strategy_id: str,
    request: StrategyUpdateRequest,
    service: WorkbenchApplicationService = Depends(get_workbench_service),
) -> StrategyConfig:
    try:
        return service.update_strategy(strategy_id=strategy_id, request=request)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
