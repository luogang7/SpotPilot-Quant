from fastapi import APIRouter, Depends, Query

from app.api.v1.dependencies import get_workbench_service
from app.application.workbench import WorkbenchApplicationService
from app.domain.models import DashboardResponse

router = APIRouter()


@router.get("", response_model=DashboardResponse)
def get_dashboard(
    refresh: bool = Query(default=False),
    service: WorkbenchApplicationService = Depends(get_workbench_service),
) -> DashboardResponse:
    return service.get_dashboard(refresh=refresh)
