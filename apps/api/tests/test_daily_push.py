import asyncio
from contextlib import contextmanager
from typing import Iterator

import httpx

from app.application.runtime_scheduler import DailyPushScheduler, normalize_schedule_times
from app.application.workbench import WorkbenchApplicationService
from app.core.config import Settings
from app.domain.models import DailyPushResult, NotificationResult
from app.infrastructure.repositories.memory import (
    EmptyAiAnalysisRepository,
    EmptyAuditLogRepository,
    EmptyPortfolioRepository,
    EmptyRiskRepository,
    EmptyStrategyRepository,
    EmptySystemStateRepository,
)


def make_service(settings: Settings | None = None) -> WorkbenchApplicationService:
    return WorkbenchApplicationService(
        settings=settings
        or Settings(
            _env_file=None,
            ENABLE_PUBLIC_EXCHANGE_DATA=False,
            REPOSITORY_BACKEND="memory",
        ),
        portfolio_repository=EmptyPortfolioRepository(),
        strategy_repository=EmptyStrategyRepository(),
        audit_log_repository=EmptyAuditLogRepository(),
        risk_repository=EmptyRiskRepository(),
        ai_analysis_repository=EmptyAiAnalysisRepository(),
        system_state_repository=EmptySystemStateRepository(),
    )


def test_normalize_schedule_times_uses_unique_sorted_valid_values() -> None:
    assert normalize_schedule_times("18:00,09:30,invalid,18:00", fallback_time="12:00") == [
        "09:30",
        "18:00",
    ]
    assert normalize_schedule_times("", fallback_time="25:99") == ["18:00"]


def test_daily_push_without_channels_returns_explicit_failure() -> None:
    result = make_service().send_daily_push()

    assert result.success is False
    assert result.results[0].provider == "all"
    assert "no notification channels configured" in result.results[0].message
    assert "🎯 今日结论" in result.message


def test_daily_push_sends_wecom_markdown_report(monkeypatch) -> None:
    sent: dict[str, object] = {}

    def fake_post(url: str, json: dict[str, object], timeout: int) -> httpx.Response:
        sent.update({"url": url, "json": json, "timeout": timeout})
        return httpx.Response(200, request=httpx.Request("POST", url))

    monkeypatch.setattr("app.application.notifications.httpx.post", fake_post)
    service = make_service(
        Settings(
            _env_file=None,
            ENABLE_PUBLIC_EXCHANGE_DATA=False,
            REPOSITORY_BACKEND="memory",
            WECOM_WEBHOOK_URL="https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=test",
        ),
    )

    result = service.send_daily_push()

    assert result.success is True
    assert result.results[0].provider == "wecom"
    assert sent["url"] == "https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=test"
    assert sent["timeout"] == 10
    payload = sent["json"]
    assert isinstance(payload, dict)
    assert payload["msgtype"] == "markdown"
    content = payload["markdown"]["content"]  # type: ignore[index]
    assert "SpotPilot Quant 每日量化日报" in content
    assert "# SpotPilot Quant 每日量化日报" not in content
    assert "🎯 今日结论" in content
    assert "📊 行情与 AI" in content
    assert "🔔 系统提醒" in content
    assert "BTC/USDT" in content


def test_daily_push_scheduler_run_once_uses_service_factory() -> None:
    calls: list[str] = []
    settings = Settings(_env_file=None, SCHEDULE_ENABLED=True, REPOSITORY_BACKEND="memory")

    class StubService:
        def send_daily_push(self) -> DailyPushResult:
            calls.append("sent")
            return DailyPushResult(
                success=True,
                title="daily",
                message="done",
                results=[NotificationResult(success=True, provider="wecom", message="ok")],
            )

    @contextmanager
    def service_context(_settings: Settings) -> Iterator[StubService]:
        yield StubService()

    scheduler = DailyPushScheduler(
        settings_provider=lambda: settings,
        service_context_factory=service_context,
        poll_interval_seconds=1,
    )

    asyncio.run(scheduler.run_once(run_reason="test"))

    assert calls == ["sent"]
