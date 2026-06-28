from fastapi import APIRouter, Depends, HTTPException

from app.api.v1.dependencies import get_settings_cached, get_workbench_service
from app.application.workbench import WorkbenchApplicationService
from app.core.config import get_settings
from app.domain.models import (
    AiProxyConnectionTestRequest,
    AiProxyConnectionTestResult,
    AiProxySettingsUpdateRequest,
    DailyPushResult,
    DailyPushSettingsUpdateRequest,
    ExchangeAccountConnectionTestRequest,
    ExchangeAccountConnectionTestResult,
    ExchangeAccountSettingsUpdateRequest,
    NotificationResult,
    NotificationSettingsUpdateRequest,
    NotificationTestRequest,
    SettingsSummary,
)

router = APIRouter()


@router.get("/summary", response_model=SettingsSummary)
def get_settings_summary(
    service: WorkbenchApplicationService = Depends(get_workbench_service),
) -> SettingsSummary:
    return service.get_settings_summary()


@router.put("/ai-proxies", response_model=SettingsSummary)
def update_ai_proxy_settings(
    request: AiProxySettingsUpdateRequest,
    service: WorkbenchApplicationService = Depends(get_workbench_service),
) -> SettingsSummary:
    try:
        summary = service.update_ai_proxy_settings(request)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    get_settings.cache_clear()
    get_settings_cached.cache_clear()
    return summary


@router.post("/ai-proxies/test", response_model=AiProxyConnectionTestResult)
def test_ai_proxy_connection(
    request: AiProxyConnectionTestRequest,
    service: WorkbenchApplicationService = Depends(get_workbench_service),
) -> AiProxyConnectionTestResult:
    return service.test_ai_proxy_connection(request)


@router.put("/exchange-accounts", response_model=SettingsSummary)
def update_exchange_account_settings(
    request: ExchangeAccountSettingsUpdateRequest,
    service: WorkbenchApplicationService = Depends(get_workbench_service),
) -> SettingsSummary:
    try:
        summary = service.update_exchange_account_settings(request)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    get_settings.cache_clear()
    get_settings_cached.cache_clear()
    return summary


@router.post("/exchange-accounts/test", response_model=ExchangeAccountConnectionTestResult)
def test_exchange_account_connection(
    request: ExchangeAccountConnectionTestRequest,
    service: WorkbenchApplicationService = Depends(get_workbench_service),
) -> ExchangeAccountConnectionTestResult:
    return service.test_exchange_account_connection(request)


@router.post("/notifications/test", response_model=NotificationResult)
def send_test_notification(
    request: NotificationTestRequest,
    service: WorkbenchApplicationService = Depends(get_workbench_service),
) -> NotificationResult:
    return service.send_test_notification(request)


@router.post("/notifications/daily-push/run", response_model=DailyPushResult)
def run_daily_push_notification(
    service: WorkbenchApplicationService = Depends(get_workbench_service),
) -> DailyPushResult:
    return service.send_daily_push()


@router.put("/daily-push", response_model=SettingsSummary)
def update_daily_push_settings(
    request: DailyPushSettingsUpdateRequest,
    service: WorkbenchApplicationService = Depends(get_workbench_service),
) -> SettingsSummary:
    try:
        summary = service.update_daily_push_settings(request)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    get_settings.cache_clear()
    get_settings_cached.cache_clear()
    return summary


@router.put("/notifications", response_model=SettingsSummary)
def update_notification_settings(
    request: NotificationSettingsUpdateRequest,
    service: WorkbenchApplicationService = Depends(get_workbench_service),
) -> SettingsSummary:
    try:
        summary = service.update_notification_settings(request)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    get_settings.cache_clear()
    get_settings_cached.cache_clear()
    return summary
