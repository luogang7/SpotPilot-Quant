import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy.exc import SQLAlchemyError
from starlette.responses import Response

from app.api.v1.dependencies import workbench_service_context
from app.api.v1.router import api_router
from app.application.ai import AiServiceUnavailable
from app.application.runtime_scheduler import DailyPushScheduler
from app.core.config import Settings, get_settings
from app.infrastructure.persistence.models import Base
from app.infrastructure.persistence.schema import apply_schema_migrations
from app.infrastructure.persistence.session import create_mysql_engine


API_NO_CACHE_HEADERS = {
    "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
    "Pragma": "no-cache",
    "Expires": "0",
}

logger = logging.getLogger(__name__)


def ensure_database_schema() -> None:
    settings = get_settings()
    if settings.repository_backend != "mysql":
        return
    engine = create_mysql_engine(settings)
    try:
        Base.metadata.create_all(engine)
        apply_schema_migrations(engine)
    except Exception:
        logger.warning("Database schema initialization failed; API startup will continue.", exc_info=True)
    finally:
        engine.dispose()


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    ensure_database_schema()
    scheduler = DailyPushScheduler(
        settings_provider=Settings,
        service_context_factory=workbench_service_context,
        poll_interval_seconds=get_settings().schedule_poll_interval_seconds,
    )
    scheduler.start()
    _app.state.daily_push_scheduler = scheduler
    try:
        yield
    finally:
        await scheduler.stop()


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title="SpotPilot Quant API",
        description="Local-first spot crypto quant validation and risk workbench API",
        version="0.1.0",
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=[settings.web_origin, "http://127.0.0.1:5173"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(api_router, prefix="/api/v1")

    @app.middleware("http")
    async def prevent_api_cache(request: Request, call_next) -> Response:
        response = await call_next(request)
        if request.url.path.startswith("/api/"):
            for header, value in API_NO_CACHE_HEADERS.items():
                response.headers[header] = value
            for header in ("etag", "last-modified"):
                if header in response.headers:
                    del response.headers[header]
        return response

    @app.exception_handler(AiServiceUnavailable)
    async def ai_service_unavailable_handler(
        request: Request,
        exc: AiServiceUnavailable,
    ) -> JSONResponse:
        return JSONResponse(status_code=503, content={"detail": str(exc)})

    @app.exception_handler(SQLAlchemyError)
    async def database_unavailable_handler(
        request: Request,
        exc: SQLAlchemyError,
    ) -> JSONResponse:
        logger.warning("Database request failed.", exc_info=True)
        return JSONResponse(
            status_code=503,
            content={"detail": "数据库连接不可用，请确认本地 MySQL 已启动并且 .env 端口配置正确。"},
        )

    return app


app = create_app()
