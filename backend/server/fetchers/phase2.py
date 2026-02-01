from __future__ import annotations

import json
import logging
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

from .http import fetch_first_ok
from .phase1 import FetchContext


log = logging.getLogger("hamclock-backend.fetchers.phase2")


def _atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(content, encoding="utf-8")
    tmp.replace(path)


def _parse_time(value: str) -> Optional[datetime]:
    for fmt in (
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d %H:%M:%S.%f",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%dT%H:%M:%S.%f",
        "%Y-%m-%dT%H:%M:%SZ",
        "%Y-%m-%dT%H:%M:%S.%fZ",
    ):
        try:
            return datetime.strptime(value, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


def _load_json(urls: Iterable[str], ctx: FetchContext) -> Optional[object]:
    try:
        raw = fetch_first_ok(urls, ctx.timeout, ctx.user_agent).content
        return json.loads(raw)
    except Exception as exc:  # noqa: BLE001
        log.warning("JSON fetch failed: %s", exc)
        return None


def _tail(items: List, count: int) -> List:
    if len(items) <= count:
        return items
    return items[-count:]


def _load_daily_solar_indices(ctx: FetchContext) -> List[Tuple[datetime, float, float]]:
    url = "https://services.swpc.noaa.gov/text/daily-solar-indices.txt"
    try:
        raw = fetch_first_ok([url], ctx.timeout, ctx.user_agent).content.decode("utf-8", errors="replace")
    except Exception as exc:  # noqa: BLE001
        log.warning("daily-solar-indices fetch failed: %s", exc)
        return []
    rows: List[Tuple[datetime, float, float]] = []
    for line in raw.splitlines():
        line = line.strip()
        if not line or not line[0].isdigit():
            continue
        parts = line.split()
        if len(parts) < 5:
            continue
        try:
            year = int(parts[0])
            month = int(parts[1])
            day = int(parts[2])
            flux = float(parts[3])
            ssn = float(parts[4])
        except Exception:
            continue
        dt = datetime(year, month, day, tzinfo=timezone.utc)
        rows.append((dt, flux, ssn))
    return rows


def update_ssn(ctx: FetchContext) -> bool:
    rows = _load_daily_solar_indices(ctx)
    if not rows:
        return False
    entries = _tail(rows, 31)
    output = [f"{dt.year:04d} {dt.month:02d} {dt.day:02d} {ssn:.0f}" for dt, _, ssn in entries]
    target = ctx.data_root / "ssn" / "ssn-31.txt"
    _atomic_write(target, "\n".join(output) + "\n")
    return True


def update_ssn_history(ctx: FetchContext) -> bool:
    rows = _load_daily_solar_indices(ctx)
    if not rows:
        return False
    buckets: Dict[int, List[float]] = {}
    for dt, _, ssn in rows:
        buckets.setdefault(dt.year, []).append(ssn)
    output: List[str] = []
    for year in sorted(buckets):
        values = buckets[year]
        if values:
            avg = sum(values) / len(values)
            output.append(f"{year} {avg:.1f}")
    if not output:
        return False
    target = ctx.data_root / "ssn" / "ssn-history.txt"
    _atomic_write(target, "\n".join(output) + "\n")
    return True


def _load_27_day_outlook(ctx: FetchContext) -> List[float]:
    url = "https://services.swpc.noaa.gov/text/27-day-outlook.txt"
    try:
        raw = fetch_first_ok([url], ctx.timeout, ctx.user_agent).content.decode("utf-8", errors="replace")
    except Exception as exc:  # noqa: BLE001
        log.warning("27-day outlook fetch failed: %s", exc)
        return []
    values: List[float] = []
    for line in raw.splitlines():
        line = line.strip()
        if not line or not line[0].isdigit():
            continue
        parts = line.split()
        if len(parts) < 4:
            continue
        try:
            values.append(float(parts[3]))
        except Exception:
            continue
    return values


def update_solar_flux(ctx: FetchContext) -> bool:
    rows = _load_daily_solar_indices(ctx)
    if not rows:
        return False
    flux_values = [flux for _, flux, _ in rows]
    history = _tail(flux_values, 72)
    outlook = _load_27_day_outlook(ctx)
    combined = history + outlook
    if not combined:
        return False
    if len(combined) < 99:
        combined.extend([combined[-1]] * (99 - len(combined)))
    combined = combined[:99]
    output = [f"{value:.0f}" for value in combined]
    target = ctx.data_root / "solar-flux" / "solarflux-99.txt"
    _atomic_write(target, "\n".join(output) + "\n")
    return True


def update_solar_flux_history(ctx: FetchContext) -> bool:
    rows = _load_daily_solar_indices(ctx)
    if not rows:
        return False
    buckets: Dict[int, List[float]] = {}
    for dt, flux, _ in rows:
        buckets.setdefault(dt.year, []).append(flux)
    output: List[str] = []
    for year in sorted(buckets):
        values = buckets[year]
        if values:
            avg = sum(values) / len(values)
            output.append(f"{year} {avg:.2f}")
    if not output:
        return False
    target = ctx.data_root / "solar-flux" / "solarflux-history.txt"
    _atomic_write(target, "\n".join(output) + "\n")
    return True


def update_kindex(ctx: FetchContext) -> bool:
    urls = ["https://services.swpc.noaa.gov/products/noaa-planetary-k-index.json"]
    data = _load_json(urls, ctx)
    if not isinstance(data, list) or len(data) < 2:
        return False

    header = data[0]
    rows = data[1:]
    kp_index = 0
    if isinstance(header, list):
        for i, name in enumerate(header):
            if str(name).lower() in ("kp_index", "kp", "kp_index_3h"):
                kp_index = i
                break
            if str(name).lower() == "kp":
                kp_index = i
                break

    values: List[str] = []
    for row in rows:
        if not isinstance(row, list) or len(row) <= kp_index:
            continue
        try:
            values.append(f"{float(row[kp_index]):.2f}")
        except Exception:
            continue

    values = _tail(values, 72)
    if not values:
        return False

    target = ctx.data_root / "geomag" / "kindex.txt"
    _atomic_write(target, "\n".join(values) + "\n")
    return True


def update_xray(ctx: FetchContext) -> bool:
    url = "https://services.swpc.noaa.gov/json/goes/primary/xrays-7-day.json"
    data = _load_json([url], ctx)
    if not isinstance(data, list) or not data:
        return False

    short_band: Dict[str, float] = {}
    long_band: Dict[str, float] = {}
    for entry in data:
        if not isinstance(entry, dict):
            continue
        time_tag = entry.get("time_tag") or entry.get("time-tag")
        flux = entry.get("flux")
        energy = entry.get("energy") or entry.get("energy_band")
        if time_tag is None or flux is None or energy is None:
            continue
        energy = str(energy)
        if "0.05" in energy:
            short_band[str(time_tag)] = float(flux)
        elif "0.1" in energy:
            long_band[str(time_tag)] = float(flux)

    all_times = sorted(set(short_band) | set(long_band))
    lines: List[str] = []
    for time_tag in all_times:
        dt = _parse_time(time_tag)
        if dt is None:
            continue
        short = short_band.get(time_tag, 1e-9)
        long = long_band.get(time_tag, 1e-9)
        hhmm = dt.hour * 100 + dt.minute
        line = f"{dt.year:4d} {dt.month:2d} {dt.day:2d} {hhmm:5d}   00000  00000 {short:11.2e} {long:11.2e}"
        lines.append(line)

    if not lines:
        return False

    target = ctx.data_root / "xray" / "xray.txt"
    _atomic_write(target, "\n".join(lines) + "\n")
    return True


def update_solar_wind(ctx: FetchContext) -> bool:
    urls = [
        "https://services.swpc.noaa.gov/products/solar-wind/plasma-7-day.json",
        "https://services.swpc.noaa.gov/json/dscovr/dscovr_plasma_5m.json",
    ]
    data = _load_json(urls, ctx)
    if not isinstance(data, list) or len(data) < 2:
        return False

    header = data[0]
    rows = data[1:]
    time_idx = 0
    dens_idx = 1
    speed_idx = 2
    if isinstance(header, list):
        for i, name in enumerate(header):
            lname = str(name).lower()
            if lname == "time_tag":
                time_idx = i
            elif lname == "density":
                dens_idx = i
            elif lname == "speed":
                speed_idx = i

    cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
    lines: List[str] = []
    for row in rows:
        if not isinstance(row, list) or len(row) <= max(time_idx, dens_idx, speed_idx):
            continue
        dt = _parse_time(str(row[time_idx]))
        if dt is None or dt < cutoff:
            continue
        try:
            density = float(row[dens_idx])
            speed = float(row[speed_idx])
        except Exception:
            continue
        lines.append(f"{int(dt.timestamp())} {density:.2f} {speed:.1f}")

    if not lines:
        return False

    target = ctx.data_root / "solar-wind" / "swind-24hr.txt"
    _atomic_write(target, "\n".join(lines) + "\n")
    return True


def update_bz(ctx: FetchContext) -> bool:
    urls = [
        "https://services.swpc.noaa.gov/products/solar-wind/mag-7-day.json",
        "https://services.swpc.noaa.gov/json/dscovr/dscovr_mag_5m.json",
    ]
    data = _load_json(urls, ctx)
    if not isinstance(data, list) or len(data) < 2:
        return False

    header = data[0]
    rows = data[1:]
    time_idx = 0
    bx_idx = 1
    by_idx = 2
    bz_idx = 3
    bt_idx = 4
    if isinstance(header, list):
        for i, name in enumerate(header):
            lname = str(name).lower()
            if lname == "time_tag":
                time_idx = i
            elif lname == "bx_gsm":
                bx_idx = i
            elif lname == "by_gsm":
                by_idx = i
            elif lname == "bz_gsm":
                bz_idx = i
            elif lname == "bt":
                bt_idx = i

    cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
    lines: List[str] = ["# UNIX        Bx     By     Bz     Bt"]
    for row in rows:
        if not isinstance(row, list) or len(row) <= max(time_idx, bx_idx, by_idx, bz_idx, bt_idx):
            continue
        dt = _parse_time(str(row[time_idx]))
        if dt is None or dt < cutoff:
            continue
        try:
            bx = float(row[bx_idx])
            by = float(row[by_idx])
            bz = float(row[bz_idx])
            bt = float(row[bt_idx])
        except Exception:
            continue
        lines.append(f"{int(dt.timestamp())} {bx:6.1f} {by:6.1f} {bz:6.1f} {bt:6.1f}")

    if len(lines) <= 1:
        return False

    target = ctx.data_root / "Bz" / "Bz.txt"
    _atomic_write(target, "\n".join(lines) + "\n")
    return True


def update_noaa_scales(ctx: FetchContext) -> bool:
    url = "https://services.swpc.noaa.gov/products/noaa-scales.json"
    data = _load_json([url], ctx)
    if not isinstance(data, dict):
        return False

    def _extract(scale_key: str) -> List[int]:
        values = data.get(scale_key, {})
        if isinstance(values, dict):
            forecast = values.get("forecast", [])
            if isinstance(forecast, list) and forecast:
                return [int(item.get("scale", 0)) for item in forecast[:4]]
        return [0, 0, 0, 0]

    r_vals = _extract("R")
    s_vals = _extract("S")
    g_vals = _extract("G")

    output = [
        f"R  {r_vals[0]} {r_vals[1]} {r_vals[2]} {r_vals[3]}",
        f"S  {s_vals[0]} {s_vals[1]} {s_vals[2]} {s_vals[3]}",
        f"G  {g_vals[0]} {g_vals[1]} {g_vals[2]} {g_vals[3]}",
    ]

    target = ctx.data_root / "NOAASpaceWX" / "noaaswx.txt"
    _atomic_write(target, "\n".join(output) + "\n")
    return True


def update_aurora(ctx: FetchContext) -> bool:
    urls = [
        "https://services.swpc.noaa.gov/json/ovation_aurora_latest.json",
        "https://services.swpc.noaa.gov/products/aurora-30-minute-forecast.json",
    ]
    data = _load_json(urls, ctx)
    lines: List[str] = []

    if isinstance(data, list) and data:
        header = data[0]
        rows = data[1:]
        time_idx = None
        value_idx = None
        if isinstance(header, list):
            for i, name in enumerate(header):
                lname = str(name).lower()
                if lname in ("time_tag", "forecast_time"):
                    time_idx = i
                elif lname in ("value", "kp", "forecast"):
                    value_idx = i
        if time_idx is not None and value_idx is not None:
            for row in rows:
                if not isinstance(row, list) or len(row) <= max(time_idx, value_idx):
                    continue
                dt = _parse_time(str(row[time_idx]))
                if dt is None:
                    continue
                try:
                    value = float(row[value_idx])
                except Exception:
                    continue
                lines.append(f"{int(dt.timestamp())} {value:.0f}")

    if not lines and isinstance(data, dict):
        coords = data.get("coordinates") or data.get("data")
        time_tag = data.get("Forecast Time") or data.get("Observation Time") or data.get("time_tag")
        dt = _parse_time(str(time_tag)) if time_tag else None
        if isinstance(coords, list) and dt is not None:
            values = []
            for item in coords:
                if isinstance(item, list) and len(item) >= 3:
                    try:
                        values.append(float(item[2]))
                    except Exception:
                        continue
            if values:
                lines.append(f"{int(dt.timestamp())} {max(values):.0f}")

    if not lines:
        return False

    target = ctx.data_root / "aurora" / "aurora.txt"
    _atomic_write(target, "\n".join(lines) + "\n")
    return True


def update_dst(ctx: FetchContext) -> bool:
    url = "https://services.swpc.noaa.gov/products/kyoto-dst.json"
    data = _load_json([url], ctx)
    lines: List[str] = []
    if isinstance(data, list) and data:
        header = data[0]
        rows = data[1:]
        time_idx = None
        dst_idx = None
        if isinstance(header, list):
            for i, name in enumerate(header):
                lname = str(name).lower()
                if lname in ("time_tag", "time", "time_tag_utc"):
                    time_idx = i
                elif lname in ("dst", "dst_index"):
                    dst_idx = i
        if time_idx is not None and dst_idx is not None:
            for row in rows:
                if not isinstance(row, list) or len(row) <= max(time_idx, dst_idx):
                    continue
                dt = _parse_time(str(row[time_idx]))
                if dt is None:
                    continue
                try:
                    value = int(float(row[dst_idx]))
                except Exception:
                    continue
                lines.append(f"{dt.strftime('%Y-%m-%dT%H:%M:%S')} {value}")
    elif isinstance(data, dict):
        entries = data.get("data") or data.get("values") or []
        if isinstance(entries, list):
            for entry in entries:
                if not isinstance(entry, dict):
                    continue
                time_tag = entry.get("time_tag") or entry.get("time")
                value = entry.get("dst")
                dt = _parse_time(str(time_tag)) if time_tag else None
                if dt is None or value is None:
                    continue
                try:
                    value_i = int(float(value))
                except Exception:
                    continue
                lines.append(f"{dt.strftime('%Y-%m-%dT%H:%M:%S')} {value_i}")
    if not lines:
        return False
    target = ctx.data_root / "dst" / "dst.txt"
    _atomic_write(target, "\n".join(lines) + "\n")
    return True


def _flatten_values(obj) -> List[float]:
    values: List[float] = []
    if isinstance(obj, list):
        for item in obj:
            values.extend(_flatten_values(item))
    elif isinstance(obj, (int, float)):
        values.append(float(obj))
    return values


def update_drap(ctx: FetchContext) -> bool:
    url = "https://services.swpc.noaa.gov/products/animations/d-rap/global.json"
    data = _load_json([url], ctx)
    lines: List[str] = []

    def _emit_from_entry(entry: dict) -> None:
        time_tag = entry.get("time_tag") or entry.get("time") or entry.get("Observation Time")
        grid = entry.get("data") or entry.get("values") or entry.get("grid") or entry.get("coordinates")
        dt = _parse_time(str(time_tag)) if time_tag else None
        if dt is None or grid is None:
            return
        values = _flatten_values(grid)
        if not values:
            return
        min_v = min(values)
        max_v = max(values)
        mean_v = sum(values) / len(values)
        lines.append(f"{int(dt.timestamp())} : {min_v:.1f} {max_v:.1f} {mean_v:.5f}")

    if isinstance(data, list):
        for entry in data:
            if isinstance(entry, dict):
                _emit_from_entry(entry)
    elif isinstance(data, dict):
        _emit_from_entry(data)

    if not lines:
        return False

    target = ctx.data_root / "drap" / "stats.txt"
    _atomic_write(target, "\n".join(lines) + "\n")
    return True


PHASE2_JOBS = [
    {"id": "update_ssn", "func": update_ssn, "trigger": "interval", "hours": 1, "replace_existing": True},
    {"id": "update_ssn_history", "func": update_ssn_history, "trigger": "interval", "hours": 24, "replace_existing": True},
    {"id": "update_solar_flux", "func": update_solar_flux, "trigger": "interval", "hours": 1, "replace_existing": True},
    {"id": "update_solar_flux_history", "func": update_solar_flux_history, "trigger": "interval", "hours": 24, "replace_existing": True},
    {"id": "update_kindex", "func": update_kindex, "trigger": "interval", "hours": 1, "replace_existing": True},
    {"id": "update_xray", "func": update_xray, "trigger": "interval", "minutes": 5, "replace_existing": True},
    {"id": "update_solar_wind", "func": update_solar_wind, "trigger": "interval", "minutes": 5, "replace_existing": True},
    {"id": "update_bz", "func": update_bz, "trigger": "interval", "minutes": 5, "replace_existing": True},
    {"id": "update_noaa_scales", "func": update_noaa_scales, "trigger": "interval", "hours": 1, "replace_existing": True},
    {"id": "update_aurora", "func": update_aurora, "trigger": "interval", "minutes": 30, "replace_existing": True},
    {"id": "update_dst", "func": update_dst, "trigger": "interval", "hours": 3, "replace_existing": True},
    {"id": "update_drap", "func": update_drap, "trigger": "interval", "minutes": 15, "replace_existing": True},
]


def run_phase2(ctx: FetchContext) -> None:
    for job in PHASE2_JOBS:
        job_name = job.get("id", "phase2")
        func = job["func"]
        try:
            ok = func(ctx)
            log.info("Phase2 job %s completed: %s", job_name, ok)
        except Exception as exc:  # noqa: BLE001
            log.warning("Phase2 job %s failed: %s", job_name, exc)
