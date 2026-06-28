import asyncio
import logging
import re
from collections.abc import Callable
from contextlib import AbstractContextManager
from datetime import datetime

from app.application.workbench import WorkbenchApplicationService
from app.core.config import Settings

logger = logging.getLogger(__name__)


ScheduleSettingsProvider = Callable[[], Settings]
WorkbenchServiceContextFactory = Callable[
    [Settings],
    AbstractContextManager[WorkbenchApplicationService],
]


def normalize_schedule_times(
    schedule_times: str | list[str] | tuple[str, ...] | None,
    fallback_time: str = "18:00",
) -> list[str]:
    if isinstance(schedule_times, str):
        raw_items = [item.strip() for item in schedule_times.split(",")]
    elif schedule_times is None:
        raw_items = []
    else:
        raw_items = [str(item).strip() for item in schedule_times]

    valid = {
        item
        for item in raw_items
        if item and re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d", item)
    }
    if not valid:
        fallback = (fallback_time or "18:00").strip() or "18:00"
        valid.add(
            fallback
            if re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d", fallback)
            else "18:00",
        )
    return sorted(valid)


class DailyPushScheduler:
    def __init__(
        self,
        settings_provider: ScheduleSettingsProvider,
        service_context_factory: WorkbenchServiceContextFactory,
        poll_interval_seconds: int = 30,
    ) -> None:
        self.settings_provider = settings_provider
        self.service_context_factory = service_context_factory
        self.poll_interval_seconds = max(1, poll_interval_seconds)
        self._task: asyncio.Task[None] | None = None
        self._stop_event: asyncio.Event | None = None
        self._last_run_keys: set[str] = set()
        self._run_lock = asyncio.Lock()

    def start(self) -> None:
        if self._task is not None and not self._task.done():
            return
        self._stop_event = asyncio.Event()
        self._task = asyncio.create_task(self._run_forever(), name="daily-push-scheduler")
        logger.info("Daily push scheduler started.")

    async def stop(self) -> None:
        if self._stop_event is not None:
            self._stop_event.set()
        if self._task is not None:
            try:
                await asyncio.wait_for(self._task, timeout=5)
            except asyncio.TimeoutError:
                self._task.cancel()
                await asyncio.gather(self._task, return_exceptions=True)
        logger.info("Daily push scheduler stopped.")

    async def _run_forever(self) -> None:
        stop_event = self._stop_event
        if stop_event is None:
            return

        await self._run_startup_once_if_needed()
        while not stop_event.is_set():
            await self._run_due_once()
            try:
                await asyncio.wait_for(stop_event.wait(), timeout=self._current_poll_interval())
            except asyncio.TimeoutError:
                continue

    async def _run_startup_once_if_needed(self) -> None:
        settings = self.settings_provider()
        if not settings.schedule_enabled or not settings.schedule_run_immediately:
            return
        logger.info("Daily push configured to run immediately on startup.")
        await self.run_once(settings=settings, run_reason="startup")
        self._last_run_keys.add(self._run_key(datetime.now()))

    async def _run_due_once(self) -> None:
        settings = self.settings_provider()
        if not settings.schedule_enabled:
            return

        now = datetime.now()
        schedule_times = normalize_schedule_times(
            settings.schedule_times,
            fallback_time=settings.schedule_time,
        )
        if now.strftime("%H:%M") not in schedule_times:
            return

        run_key = self._run_key(now)
        if run_key in self._last_run_keys:
            return

        self._last_run_keys.add(run_key)
        await self.run_once(settings=settings, run_reason="schedule")

    async def run_once(self, settings: Settings | None = None, run_reason: str = "manual") -> None:
        async with self._run_lock:
            runtime_settings = settings or self.settings_provider()
            await asyncio.to_thread(self._run_sync, runtime_settings, run_reason)

    def _run_sync(self, settings: Settings, run_reason: str) -> None:
        try:
            with self.service_context_factory(settings) as service:
                result = service.send_daily_push()
        except Exception:
            logger.exception("Daily push run failed.")
            return

        logger.info(
            "Daily push run completed: reason=%s success=%s providers=%s",
            run_reason,
            result.success,
            ",".join(item.provider for item in result.results),
        )

    def _current_poll_interval(self) -> int:
        try:
            settings = self.settings_provider()
        except Exception:
            return self.poll_interval_seconds
        return max(1, settings.schedule_poll_interval_seconds or self.poll_interval_seconds)

    @staticmethod
    def _run_key(now: datetime) -> str:
        return now.strftime("%Y-%m-%d %H:%M")
