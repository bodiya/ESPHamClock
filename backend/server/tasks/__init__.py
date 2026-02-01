from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List

from ..fetchers.phase1 import FetchContext, PHASE1_JOBS


log = logging.getLogger("hamclock-backend.tasks")


def heartbeat() -> None:
    log.info("Scheduler heartbeat at %s", datetime.now(timezone.utc).isoformat())


def build_context(app) -> FetchContext:
    return FetchContext(
        data_root=app.config["DATA_ROOT"],
        timeout=app.config.get("FETCHER_TIMEOUT", 15.0),
        user_agent=app.config["FETCHER_USER_AGENT"],
        hamclock_version=app.config.get("HAMCLOCK_VERSION"),
        hamclock_version_info=app.config.get("HAMCLOCK_VERSION_INFO"),
    )


def get_jobs(app) -> List[Dict[str, Any]]:
    ctx = build_context(app)
    jobs: List[Dict[str, Any]] = [
        {
            "id": "heartbeat",
            "func": heartbeat,
            "trigger": "interval",
            "minutes": 60,
            "replace_existing": True,
        }
    ]

    for job in PHASE1_JOBS:
        job_copy = dict(job)
        job_copy["args"] = [ctx]
        jobs.append(job_copy)

    return jobs
