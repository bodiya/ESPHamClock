from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

from apscheduler.schedulers.background import BackgroundScheduler

from .tasks import get_jobs


log = logging.getLogger("hamclock-backend.scheduler")


_scheduler: Optional[BackgroundScheduler] = None


def start_scheduler(app) -> BackgroundScheduler:
    global _scheduler
    if _scheduler is not None:
        return _scheduler

    scheduler = BackgroundScheduler(timezone="UTC")

    for job in get_jobs(app):
        scheduler.add_job(**job)

    scheduler.start()
    log.info("Scheduler started with %d jobs", len(scheduler.get_jobs()))
    _scheduler = scheduler
    return scheduler


