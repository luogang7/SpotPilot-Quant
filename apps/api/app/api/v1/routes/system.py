from fastapi import APIRouter, Depends, Query

from app.api.v1.dependencies import get_workbench_service
from app.application.workbench import WorkbenchApplicationService
from app.domain.models import SystemControlState, SystemControlUpdateRequest, SystemStatus

router = APIRouter()


@router.get("/status", response_model=SystemStatus)
def status(
    probe: bool = Query(default=False),
    service: WorkbenchApplicationService = Depends(get_workbench_service),
) -> SystemStatus:
    return service.get_system_status(probe=probe)


@router.put("/control", response_model=SystemControlState)
def update_control(
    request: SystemControlUpdateRequest,
    service: WorkbenchApplicationService = Depends(get_workbench_service),
) -> SystemControlState:
    return service.update_system_control(request)
