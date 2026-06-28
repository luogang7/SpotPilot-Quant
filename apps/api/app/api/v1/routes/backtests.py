from fastapi import APIRouter, Depends, HTTPException, Response

from app.api.v1.dependencies import get_workbench_service
from app.application.backtesting import export_backtest_result
from app.application.workbench import WorkbenchApplicationService
from app.domain.models import BacktestRequest, BacktestResult

router = APIRouter()


@router.post("/run", response_model=BacktestResult)
def run_backtest(
    request: BacktestRequest,
    service: WorkbenchApplicationService = Depends(get_workbench_service),
) -> BacktestResult:
    return service.run_backtest(request)


@router.post("/export")
def export_backtest(
    request: BacktestRequest,
    format: str = "json",
    service: WorkbenchApplicationService = Depends(get_workbench_service),
) -> Response:
    try:
        media_type, extension, content = export_backtest_result(service.run_backtest(request), format)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    filename = (
        f"backtest_{request.strategy_id}_{request.exchange.value}_"
        f"{request.symbol.replace('/', '-')}_{request.start_date}_{request.end_date}.{extension}"
    )
    return Response(
        content=content,
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
