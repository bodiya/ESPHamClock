from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple

from .fetchers.phase1 import (
    ingest_cities,
    derive_cities,
    ingest_cty,
    derive_cty,
    ingest_esats,
    derive_esats,
    ingest_version,
    derive_version,
    FetchContext,
)
from .fetchers.phase2 import (
    ingest_daily_solar_indices,
    ingest_solar_indices,
    derive_ssn,
    derive_ssn_history,
    derive_solar_flux,
    derive_solar_flux_history,
    ingest_kindex,
    derive_kindex,
    ingest_solar_wind,
    derive_solar_wind,
    ingest_bz,
    derive_bz,
    ingest_noaa_scales,
    derive_noaa_scales,
    ingest_dst,
    derive_dst,
    ingest_drap,
    derive_drap,
    ingest_xray,
    derive_xray,
    ingest_aurora,
    derive_aurora,
)
from .fetchers.phase3 import ingest_onta, derive_onta, ingest_rss, derive_rss
from .fetchers.phase4 import ingest_worldwx, derive_worldwx


log = logging.getLogger("hamclock-backend.datasources")


@dataclass
class DataSource:
    name: str
    ingest: Optional[Callable[[FetchContext], bool]] = None
    derive: Optional[Callable[[FetchContext], bool]] = None
    ingest_schedule: Optional[Dict[str, Any]] = None
    derive_schedule: Optional[Dict[str, Any]] = None
    derived_paths: List[Path] = field(default_factory=list)
    raw_paths: List[Path] = field(default_factory=list)
    expected_lines: Optional[int] = None
    expected_lines_exact: bool = False
    max_age_seconds: Optional[int] = None
    time_spacing_seconds: Optional[int] = None
    time_parser: Optional[Callable[[str], Optional[int]]] = None


def _parse_unix_first_token(line: str) -> Optional[int]:
    parts = line.split()
    if not parts:
        return None
    try:
        return int(float(parts[0]))
    except Exception:
        return None


def _parse_xray_line(line: str) -> Optional[int]:
    parts = line.split()
    if len(parts) < 4:
        return None
    try:
        year = int(parts[0])
        month = int(parts[1])
        day = int(parts[2])
        hhmm = int(parts[3])
    except Exception:
        return None
    hour = hhmm // 100
    minute = hhmm % 100
    dt = datetime(year, month, day, hour, minute, tzinfo=timezone.utc)
    return int(dt.timestamp())


GOLD_ROOT = Path(__file__).resolve().parents[1] / "gold"


def _gold_line_count(rel_path: Path) -> Optional[int]:
    path = GOLD_ROOT / rel_path
    if not path.exists():
        return None
    try:
        lines = [line for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    except Exception:
        return None
    return len(lines) if lines else None


def _gold_expected(rel_paths: Iterable[Path]) -> Tuple[Optional[int], bool]:
    for rel_path in rel_paths:
        count = _gold_line_count(rel_path)
        if count is not None:
            return count, True
    return None, False


def _build_sources() -> Dict[str, DataSource]:
    sources = [
        DataSource(
            name="cities",
            ingest=ingest_cities,
            derive=derive_cities,
            ingest_schedule={"trigger": "interval", "days": 30, "replace_existing": True},
            derive_schedule={"trigger": "interval", "days": 30, "replace_existing": True},
            raw_paths=[Path("raw") / "cities" / "cities15000.zip"],
            derived_paths=[Path("cities2.txt")],
            expected_lines=1000,
            max_age_seconds=30 * 24 * 3600,
        ),
        DataSource(
            name="cty",
            ingest=ingest_cty,
            derive=derive_cty,
            ingest_schedule={"trigger": "interval", "days": 30, "replace_existing": True},
            derive_schedule={"trigger": "interval", "days": 30, "replace_existing": True},
            raw_paths=[Path("raw") / "cty" / "cty_wt_mod.dat"],
            derived_paths=[Path("cty") / "cty_wt_mod-ll-dxcc.txt"],
            expected_lines=1000,
            max_age_seconds=30 * 24 * 3600,
        ),
        DataSource(
            name="esats",
            ingest=ingest_esats,
            derive=derive_esats,
            ingest_schedule={"trigger": "interval", "hours": 3, "replace_existing": True},
            derive_schedule={"trigger": "interval", "hours": 3, "replace_existing": True},
            raw_paths=[Path("raw") / "esats" / "amateur.tle"],
            derived_paths=[Path("esats") / "esats.txt"],
            expected_lines=10,
            max_age_seconds=6 * 3600,
        ),
        DataSource(
            name="version",
            ingest=ingest_version,
            derive=derive_version,
            ingest_schedule={"trigger": "interval", "hours": 12, "replace_existing": True},
            derive_schedule={"trigger": "interval", "hours": 12, "replace_existing": True},
            raw_paths=[Path("raw") / "version.json"],
            derived_paths=[Path("version.txt")],
            expected_lines=1,
            max_age_seconds=24 * 3600,
        ),
        DataSource(
            name="ssn",
            ingest=ingest_daily_solar_indices,
            derive=derive_ssn,
            ingest_schedule={"trigger": "interval", "hours": 6, "replace_existing": True},
            derive_schedule={"trigger": "interval", "hours": 1, "replace_existing": True},
            raw_paths=[Path("raw") / "solar" / "daily-solar-indices.txt"],
            derived_paths=[Path("ssn") / "ssn-31.txt"],
            expected_lines=31,
            max_age_seconds=6 * 3600,
        ),
        DataSource(
            name="ssn_history",
            ingest=ingest_daily_solar_indices,
            derive=derive_ssn_history,
            ingest_schedule={"trigger": "interval", "hours": 6, "replace_existing": True},
            derive_schedule={"trigger": "interval", "hours": 24, "replace_existing": True},
            raw_paths=[Path("raw") / "solar" / "daily-solar-indices.txt"],
            derived_paths=[Path("ssn") / "ssn-history.txt"],
            expected_lines=365,
            max_age_seconds=48 * 3600,
        ),
        DataSource(
            name="solar_flux",
            ingest=ingest_solar_indices,
            derive=derive_solar_flux,
            ingest_schedule={"trigger": "interval", "hours": 6, "replace_existing": True},
            derive_schedule={"trigger": "interval", "hours": 1, "replace_existing": True},
            raw_paths=[Path("raw") / "solar" / "daily-solar-indices.txt"],
            derived_paths=[Path("solar-flux") / "solarflux-99.txt"],
            expected_lines=99,
            max_age_seconds=6 * 3600,
        ),
        DataSource(
            name="solar_flux_history",
            ingest=ingest_daily_solar_indices,
            derive=derive_solar_flux_history,
            ingest_schedule={"trigger": "interval", "hours": 6, "replace_existing": True},
            derive_schedule={"trigger": "interval", "hours": 24, "replace_existing": True},
            raw_paths=[Path("raw") / "solar" / "daily-solar-indices.txt"],
            derived_paths=[Path("solar-flux") / "solarflux-history.txt"],
            expected_lines=365,
            max_age_seconds=48 * 3600,
        ),
        DataSource(
            name="kindex",
            ingest=ingest_kindex,
            derive=derive_kindex,
            ingest_schedule={"trigger": "interval", "hours": 1, "replace_existing": True},
            derive_schedule={"trigger": "interval", "hours": 1, "replace_existing": True},
            raw_paths=[Path("raw") / "geomag" / "noaa-planetary-k-index.json"],
            derived_paths=[Path("geomag") / "kindex.txt"],
            expected_lines=10,
            max_age_seconds=6 * 3600,
        ),
        DataSource(
            name="xray",
            ingest=ingest_xray,
            derive=derive_xray,
            ingest_schedule={"trigger": "interval", "minutes": 5, "replace_existing": True},
            derive_schedule={"trigger": "interval", "minutes": 1, "replace_existing": True},
            raw_paths=[Path("raw") / "xray" / "xrays-7-day.json"],
            derived_paths=[Path("xray") / "xray.txt"],
            expected_lines=150,
            max_age_seconds=5 * 60,
            time_spacing_seconds=600,
            time_parser=_parse_xray_line,
        ),
        DataSource(
            name="solar_wind",
            ingest=ingest_solar_wind,
            derive=derive_solar_wind,
            ingest_schedule={"trigger": "interval", "minutes": 5, "replace_existing": True},
            derive_schedule={"trigger": "interval", "minutes": 5, "replace_existing": True},
            raw_paths=[Path("raw") / "solar-wind" / "plasma-7-day.json"],
            derived_paths=[Path("solar-wind") / "swind-24hr.txt"],
            expected_lines=10,
            max_age_seconds=15 * 60,
            time_spacing_seconds=300,
            time_parser=_parse_unix_first_token,
        ),
        DataSource(
            name="bz",
            ingest=ingest_bz,
            derive=derive_bz,
            ingest_schedule={"trigger": "interval", "minutes": 5, "replace_existing": True},
            derive_schedule={"trigger": "interval", "minutes": 5, "replace_existing": True},
            raw_paths=[Path("raw") / "solar-wind" / "mag-7-day.json"],
            derived_paths=[Path("Bz") / "Bz.txt"],
            expected_lines=10,
            max_age_seconds=15 * 60,
            time_spacing_seconds=300,
            time_parser=_parse_unix_first_token,
        ),
        DataSource(
            name="noaa_scales",
            ingest=ingest_noaa_scales,
            derive=derive_noaa_scales,
            ingest_schedule={"trigger": "interval", "hours": 1, "replace_existing": True},
            derive_schedule={"trigger": "interval", "hours": 1, "replace_existing": True},
            raw_paths=[Path("raw") / "NOAASpaceWX" / "noaa-scales.json"],
            derived_paths=[Path("NOAASpaceWX") / "noaaswx.txt"],
            expected_lines=3,
            max_age_seconds=6 * 3600,
        ),
        DataSource(
            name="aurora",
            ingest=ingest_aurora,
            derive=derive_aurora,
            ingest_schedule={"trigger": "interval", "minutes": 30, "replace_existing": True},
            derive_schedule={"trigger": "interval", "minutes": 30, "replace_existing": True},
            raw_paths=[Path("raw") / "aurora" / "source.txt"],
            derived_paths=[Path("aurora") / "aurora.txt"],
            expected_lines=48,
            max_age_seconds=90 * 60,
            time_spacing_seconds=1800,
            time_parser=_parse_unix_first_token,
        ),
        DataSource(
            name="dst",
            ingest=ingest_dst,
            derive=derive_dst,
            ingest_schedule={"trigger": "interval", "hours": 3, "replace_existing": True},
            derive_schedule={"trigger": "interval", "hours": 3, "replace_existing": True},
            raw_paths=[Path("raw") / "dst" / "kyoto-dst.json"],
            derived_paths=[Path("dst") / "dst.txt"],
            expected_lines=10,
            max_age_seconds=6 * 3600,
        ),
        DataSource(
            name="drap",
            ingest=ingest_drap,
            derive=derive_drap,
            ingest_schedule={"trigger": "interval", "minutes": 15, "replace_existing": True},
            derive_schedule={"trigger": "interval", "minutes": 15, "replace_existing": True},
            raw_paths=[Path("raw") / "drap" / "global.json"],
            derived_paths=[Path("drap") / "stats.txt"],
            expected_lines=1,
            max_age_seconds=60 * 60,
        ),
        DataSource(
            name="onta",
            ingest=ingest_onta,
            derive=derive_onta,
            ingest_schedule={"trigger": "interval", "minutes": 5, "replace_existing": True},
            derive_schedule={"trigger": "interval", "minutes": 5, "replace_existing": True},
            raw_paths=[Path("raw") / "onta" / "activator.json"],
            derived_paths=[Path("ONTA") / "onta.txt"],
            expected_lines=1,
            max_age_seconds=60 * 60,
        ),
        DataSource(
            name="rss",
            ingest=ingest_rss,
            derive=derive_rss,
            ingest_schedule={"trigger": "interval", "hours": 1, "replace_existing": True},
            derive_schedule={"trigger": "interval", "hours": 1, "replace_existing": True},
            raw_paths=[Path("raw") / "rss" / "feeds.json"],
            derived_paths=[Path("RSS") / "web15rss.txt"],
            expected_lines=1,
            max_age_seconds=60 * 60,
        ),
        DataSource(
            name="worldwx",
            ingest=ingest_worldwx,
            derive=derive_worldwx,
            ingest_schedule={"trigger": "interval", "hours": 6, "replace_existing": True},
            derive_schedule={"trigger": "interval", "hours": 6, "replace_existing": True},
            raw_paths=[Path("raw") / "worldwx" / "index.json"],
            derived_paths=[Path("worldwx") / "wx.txt"],
            expected_lines=10,
            max_age_seconds=12 * 3600,
        ),
    ]
    for source in sources:
        gold_count, exact = _gold_expected(source.derived_paths)
        if gold_count is not None:
            source.expected_lines = gold_count
            source.expected_lines_exact = exact
    return {source.name: source for source in sources}


def get_registry() -> Dict[str, DataSource]:
    return _build_sources()


def find_source_for_path(rel_path: str) -> Optional[DataSource]:
    target = Path(rel_path)
    for source in get_registry().values():
        for path in source.derived_paths:
            if path == target:
                return source
    return None


def assess_derived_text(ctx: FetchContext, rel_path: str, text: str, mtime: Optional[float]) -> Tuple[bool, str]:
    source = find_source_for_path(rel_path)
    if not source:
        return True, ""

    if source.max_age_seconds is not None and mtime is not None:
        age = (datetime.now(timezone.utc) - datetime.fromtimestamp(mtime, tz=timezone.utc)).total_seconds()
        if age > source.max_age_seconds:
            return False, f"stale age={age:.0f}s max={source.max_age_seconds}"

    lines = [line for line in text.splitlines() if line.strip()]
    if source.expected_lines is not None:
        if source.expected_lines_exact:
            if len(lines) != source.expected_lines:
                return False, f"short lines={len(lines)} expected={source.expected_lines}"
        elif len(lines) < source.expected_lines:
            return False, f"short lines={len(lines)} expected>={source.expected_lines}"

    if source.time_spacing_seconds and source.time_parser:
        times = [source.time_parser(line) for line in lines[-10:]]
        times = [value for value in times if value is not None]
        spacing_issue = _check_spacing(times, source.time_spacing_seconds)
        if spacing_issue:
            return False, spacing_issue

    return True, ""


def run_derive(ctx: FetchContext, source: DataSource) -> bool:
    ok = True
    if source.derive:
        try:
            ok = bool(source.derive(ctx))
        except Exception as exc:  # noqa: BLE001
            log.warning("Derive %s failed: %s", source.name, exc)
            ok = False
    for rel_path in source.derived_paths:
        path = ctx.data_root / rel_path
        if not path.exists():
            log.warning("Derive %s missing output %s", source.name, path)
            ok = False
            continue
        try:
            text = path.read_text(encoding="utf-8")
            mtime = path.stat().st_mtime
        except Exception:
            log.warning("Derive %s unreadable output %s", source.name, path)
            ok = False
            path.unlink(missing_ok=True)
            continue
        valid, reason = assess_derived_text(ctx, str(rel_path), text, mtime)
        if not valid:
            log.warning("Derive %s invalid output %s: %s", source.name, path, reason)
            ok = False
            path.unlink(missing_ok=True)
    return ok


def iter_jobs(ctx: FetchContext) -> List[Dict[str, Any]]:
    jobs: List[Dict[str, Any]] = []
    for source in get_registry().values():
        if source.ingest and source.ingest_schedule:
            job = dict(source.ingest_schedule)
            job["id"] = f"ingest:{source.name}"
            job["func"] = source.ingest
            job["args"] = [ctx]
            jobs.append(job)
        if source.derive and source.derive_schedule:
            job = dict(source.derive_schedule)
            job["id"] = f"derive:{source.name}"
            job["func"] = lambda ctx, source=source: run_derive(ctx, source)
            job["args"] = [ctx]
            jobs.append(job)
    return jobs


def _check_spacing(times: List[int], expected: int) -> Optional[str]:
    if len(times) < 3:
        return None
    deltas = [b - a for a, b in zip(times, times[1:])]
    avg = sum(deltas) / len(deltas)
    if abs(avg - expected) > max(60, expected * 0.2):
        return f"time spacing off: avg {int(avg)}s expected {expected}s"
    return None


def run_health_checks(ctx: FetchContext) -> bool:
    ok = True
    now = datetime.now(timezone.utc)
    for source in get_registry().values():
        for rel_path in source.derived_paths:
            path = ctx.data_root / rel_path
            if not path.exists():
                log.warning("Health check: %s missing %s", source.name, path)
                ok = False
                continue
            try:
                text = path.read_text(encoding="utf-8")
            except Exception:
                log.warning("Health check: %s unreadable %s", source.name, path)
                ok = False
                continue
            valid, reason = assess_derived_text(ctx, str(rel_path), text, path.stat().st_mtime)
            if not valid:
                log.warning("Health check: %s %s", source.name, reason)
                ok = False
    if ok:
        log.info("Health check: all datasources healthy")
    return ok
