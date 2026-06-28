from collections.abc import Iterator
from contextlib import contextmanager
from functools import lru_cache

from app.application.workbench import WorkbenchApplicationService
from app.core.config import Settings, get_settings
from app.infrastructure.repositories.memory import (
    EmptyAiAnalysisRepository,
    EmptyAuditLogRepository,
    EmptyPortfolioRepository,
    EmptyRiskRepository,
    EmptyStrategyRepository,
    EmptySystemStateRepository,
)


memory_portfolio_repository = EmptyPortfolioRepository()
memory_strategy_repository = EmptyStrategyRepository()
memory_audit_log_repository = EmptyAuditLogRepository()
memory_risk_repository = EmptyRiskRepository()
memory_ai_analysis_repository = EmptyAiAnalysisRepository()
memory_system_state_repository = EmptySystemStateRepository()


@lru_cache
def get_settings_cached() -> Settings:
    return get_settings()


def _iter_workbench_service(settings: Settings) -> Iterator[WorkbenchApplicationService]:
    if settings.repository_backend == "mysql":
        from app.infrastructure.persistence.session import create_mysql_session_factory
        from app.infrastructure.repositories.sqlalchemy import (
            SqlAlchemyAiAnalysisRepository,
            SqlAlchemyAuditLogRepository,
            SqlAlchemyPortfolioRepository,
            SqlAlchemyRiskRepository,
            SqlAlchemyStrategyRepository,
            SqlAlchemySystemStateRepository,
        )

        session_factory = create_mysql_session_factory(settings)
        session = session_factory()
        try:
            yield WorkbenchApplicationService(
                settings=settings,
                portfolio_repository=SqlAlchemyPortfolioRepository(session),
                strategy_repository=SqlAlchemyStrategyRepository(session),
                audit_log_repository=SqlAlchemyAuditLogRepository(session),
                risk_repository=SqlAlchemyRiskRepository(session),
                ai_analysis_repository=SqlAlchemyAiAnalysisRepository(session),
                system_state_repository=SqlAlchemySystemStateRepository(session),
            )
        finally:
            session.close()
        return

    yield WorkbenchApplicationService(
        settings=settings,
        portfolio_repository=memory_portfolio_repository,
        strategy_repository=memory_strategy_repository,
        audit_log_repository=memory_audit_log_repository,
        risk_repository=memory_risk_repository,
        ai_analysis_repository=memory_ai_analysis_repository,
        system_state_repository=memory_system_state_repository,
    )


@contextmanager
def workbench_service_context(settings: Settings | None = None) -> Iterator[WorkbenchApplicationService]:
    yield from _iter_workbench_service(settings or get_settings_cached())


def get_workbench_service() -> Iterator[WorkbenchApplicationService]:
    yield from _iter_workbench_service(get_settings_cached())
