from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List


log = logging.getLogger("hamclock-backend.tasks")


def heartbeat() -> None:
    log.info("Scheduler heartbeat at %s", datetime.now(timezone.utc).isoformat())


def get_jobs(app) -> List[Dict[str, Any]]:
    # Placeholder jobs: replace with real data refresh tasks.
    return [
        {
            "id": "heartbeat",
            "func": heartbeat,
            "trigger": "interval",
            "minutes": 60,
            "replace_existing": True,
        }
    ]
