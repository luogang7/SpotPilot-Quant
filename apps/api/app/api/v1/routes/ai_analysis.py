from fastapi import APIRouter, Depends, Query

from app.api.v1.dependencies import get_workbench_service
from app.application.workbench import WorkbenchApplicationService
from app.domain.models import AiAnalysis, ExchangeId, NewsSentimentSummary

router = APIRouter()


@router.get("/latest", response_model=AiAnalysis)
def get_latest_ai_analysis(
    scope: str = Query(default="symbol", pattern="^(market|symbol)$"),
    symbol: str | None = Query(default=None),
    exchange: ExchangeId | None = Query(default=None),
    refresh: bool = Query(default=False),
    fast: bool = Query(default=False),
    service: WorkbenchApplicationService = Depends(get_workbench_service),
) -> AiAnalysis:
    return service.get_ai_analysis(
        scope=scope,
        symbol=symbol,
        exchange=exchange,
        refresh=refresh,
        prefer_cached_snapshot=fast and not refresh,
    )


@router.get("/news", response_model=NewsSentimentSummary)
def get_news_sentiment(
    symbol: str | None = Query(default=None),
    limit: int = Query(default=20, ge=1, le=50),
    refresh: bool = Query(default=False),
    service: WorkbenchApplicationService = Depends(get_workbench_service),
) -> NewsSentimentSummary:
    return service.get_news_sentiment(symbol=symbol, limit=limit, refresh=refresh)


@router.post("/validate", response_model=AiAnalysis)
def validate_ai_payload(
    payload: dict[str, object],
    service: WorkbenchApplicationService = Depends(get_workbench_service),
) -> AiAnalysis:
    return service.validate_ai_payload(payload)
