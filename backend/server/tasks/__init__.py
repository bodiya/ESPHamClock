from __future__ import annotations

import logging
from pathlib import Path
from datetime import datetime, timezone
from typing import Any, Dict, List

from ..fetchers.phase1 import FetchContext
from ..datasources import iter_jobs, run_health_checks


log = logging.getLogger("hamclock-backend.tasks")


def heartbeat() -> None:
    log.info("Scheduler heartbeat at %s", datetime.now(timezone.utc).isoformat())


def build_context(app) -> FetchContext:
    prop_data_dir = app.config.get("PROP_DATA_DIR")
    if not prop_data_dir:
        snap_path = Path("/snap/iturhfprop/current/usr/share/iturhfprop/data")
        if snap_path.exists():
            prop_data_dir = str(snap_path)
        else:
            cli_path = app.config.get("PROP_CLI_PATH")
            if cli_path:
                candidate = Path(cli_path).resolve().parent / "data"
                if candidate.exists():
                    prop_data_dir = str(candidate)

    return FetchContext(
        data_root=app.config["DATA_ROOT"],
        timeout=app.config.get("FETCHER_TIMEOUT", 15.0),
        user_agent=app.config["FETCHER_USER_AGENT"],
        hamclock_version=app.config.get("HAMCLOCK_VERSION"),
        hamclock_version_info=app.config.get("HAMCLOCK_VERSION_INFO"),
        rss_feeds=app.config.get("RSS_FEEDS"),
        geocode_cache_days=app.config.get("GEOCODE_CACHE_DAYS", 30),
        geocode_provider=app.config.get("GEOCODE_PROVIDER", "nominatim"),
        geocode_base_url=app.config.get("GEOCODE_BASE_URL", "https://nominatim.openstreetmap.org/reverse"),
        geocode_email=app.config.get("GEOCODE_EMAIL"),
        prop_enabled=app.config.get("PROP_ENABLED", False),
        prop_engine=app.config.get("PROP_ENGINE", "iturhfprop"),
        prop_cli_path=app.config.get("PROP_CLI_PATH"),
        prop_cache_dir=app.config.get("PROP_CACHE_DIR"),
        prop_data_dir=prop_data_dir,
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
    jobs.extend(iter_jobs(ctx))
    jobs.append(
        {
            "id": "health_check",
            "func": run_health_checks,
            "args": [ctx],
            "trigger": "interval",
            "minutes": 10,
            "replace_existing": True,
        }
    )

    return jobs
