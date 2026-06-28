from fastapi import APIRouter, Depends

from app.api.v1.dependencies import get_workbench_service
from app.application.workbench import WorkbenchApplicationService
from app.domain.models import RiskStatusResponse

router = APIRouter()


@router.get("/status", response_model=RiskStatusResponse)
def get_risk_status(
    service: WorkbenchApplicationService = Depends(get_workbench_service),
) -> RiskStatusResponse:
    return service.get_risk_status()
