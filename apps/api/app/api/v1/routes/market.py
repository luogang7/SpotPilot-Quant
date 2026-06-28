from datetime import datetime

from fastapi import APIRouter, Depends, Query

from app.api.v1.dependencies import get_workbench_service
from app.application.workbench import WorkbenchApplicationService
from app.domain.models import (
    ExchangeId,
    HistoricalDataSyncRequest,
    HistoricalDataSyncResult,
    MarketOverview,
)

router = APIRouter()


@router.get("/overview", response_model=MarketOverview)
def get_market_overview(
    symbol: str | None = Query(default=None),
    timeframe: str | None = Query(default=None),
    exchange: ExchangeId | None = Query(default=None),
    limit: int = Query(default=500, ge=50, le=1000),
    before: datetime | None = Query(default=None),
    refresh: bool = Query(default=False),
    fast: bool = Query(default=False),
    service: WorkbenchApplicationService = Depends(get_workbench_service),
) -> MarketOverview:
    return service.get_market_overview(
        symbol=symbol,
        timeframe=timeframe,
        exchange=exchange,
        limit=limit,
        before=before,
        prefer_live=not fast,
        refresh=refresh,
        allow_stale_local=fast,
    )


@router.post("/history/sync", response_model=HistoricalDataSyncResult)
def sync_historical_market_data(
    request: HistoricalDataSyncRequest,
    service: WorkbenchApplicationService = Depends(get_workbench_service),
) -> HistoricalDataSyncResult:
    return service.sync_historical_market_data(request)
