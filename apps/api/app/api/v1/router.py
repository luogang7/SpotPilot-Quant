from fastapi import APIRouter

from app.api.v1.routes import (
    ai_analysis,
    backtests,
    dashboard,
    health,
    logs,
    market,
    risk,
    settings,
    strategies,
    system,
    trading,
)

api_router = APIRouter()
api_router.include_router(health.router, tags=["health"])
api_router.include_router(system.router, prefix="/system", tags=["system"])
api_router.include_router(dashboard.router, prefix="/dashboard", tags=["dashboard"])
api_router.include_router(market.router, prefix="/market", tags=["market"])
api_router.include_router(strategies.router, prefix="/strategies", tags=["strategies"])
api_router.include_router(backtests.router, prefix="/backtests", tags=["backtests"])
api_router.include_router(ai_analysis.router, prefix="/ai-analysis", tags=["ai-analysis"])
api_router.include_router(trading.router, prefix="/trading", tags=["trading"])
api_router.include_router(risk.router, prefix="/risk", tags=["risk"])
api_router.include_router(logs.router, prefix="/logs", tags=["logs"])
api_router.include_router(settings.router, prefix="/settings", tags=["settings"])

