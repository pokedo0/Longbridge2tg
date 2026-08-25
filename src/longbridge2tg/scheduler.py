from __future__ import annotations

import logging
from datetime import datetime

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from .formatter import _TZ_CN


logger = logging.getLogger(__name__)


class ReportScheduler:
    def __init__(self, scheduled_report: object, times: tuple[str, ...]) -> None:
        self._scheduled_report = scheduled_report
        self._times = times
        self._scheduler = AsyncIOScheduler(timezone=_TZ_CN)

    def _configure_jobs(self) -> None:
        for index, time_text in enumerate(self._times):
            hour, minute = map(int, time_text.split(":", 1))
            self._scheduler.add_job(
                self._run_report,
                trigger=CronTrigger(hour=hour, minute=minute, timezone=_TZ_CN),
                id=f"stock-position-report-{index}",
                name=f"Longbridge stock position report at {time_text}",
                misfire_grace_time=300,
                coalesce=True,
                max_instances=1,
                replace_existing=True,
            )

    async def _run_report(self) -> None:
        await self._scheduled_report.run("定时任务")  # type: ignore[attr-defined]

    @property
    def running(self) -> bool:
        """Whether report jobs are active; the underlying scheduler may stay idle."""
        return bool(self._scheduler.get_jobs())

    def start(self) -> None:
        if self._scheduler.running:
            if self.running:
                logger.info("report jobs are already active")
                return
            self._configure_jobs()
            logger.info("started report jobs with %d daily jobs", len(self._times))
            return

        self._scheduler.start()
        self._configure_jobs()
        logger.info("started report scheduler with %d daily jobs", len(self._times))

    def stop(self) -> None:
        if not self.running:
            logger.info("report scheduler is already stopped")
            return
        self._scheduler.remove_all_jobs()
        logger.info("stopped report jobs")

    def next_run_times(self) -> list[datetime]:
        runs = [
            job.next_run_time
            for job in self._scheduler.get_jobs()
            if job.next_run_time is not None
        ]
        return sorted(runs)
