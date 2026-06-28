from fastapi import APIRouter, Depends, Query

from app.api.v1.dependencies import get_workbench_service
from app.application.workbench import WorkbenchApplicationService
from app.domain.models import AuditLog

router = APIRouter()


@router.get("", response_model=list[AuditLog])
def get_logs(
    limit: int = Query(default=20, ge=1, le=200),
    service: WorkbenchApplicationService = Depends(get_workbench_service),
) -> list[AuditLog]:
    return service.get_logs(limit=limit)
