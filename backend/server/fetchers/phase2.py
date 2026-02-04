from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

from .http import fetch_first_ok


def _read_cache(path: Path, max_age_seconds: float) -> Optional[bytes]:
    if not path.exists():
        return None
    if max_age_seconds > 0:
        age = (datetime.now(timezone.utc) - datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)).total_seconds()
        if age > max_age_seconds:
            return None
    try:
        return path.read_bytes()
    except Exception:
        return None


def _write_cache(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_bytes(data)
    tmp.replace(path)


def _read_text(path: Path, max_age_seconds: float) -> Optional[str]:
    raw = _read_cache(path, max_age_seconds)
    if raw is None:
        return None
    return raw.decode("utf-8", errors="replace")


def _write_text(path: Path, content: str) -> None:
    _write_cache(path, content.encode("utf-8"))
from .phase1 import FetchContext


log = logging.getLogger("hamclock-backend.fetchers.phase2")


def _atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(content, encoding="utf-8")
    tmp.replace(path)


def _parse_time(value: str) -> Optional[datetime]:
    value = value.strip()
    for suffix in (" UTC", "Z"):
        if value.endswith(suffix):
            value = value[: -len(suffix)]
            break
    for fmt in (
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d %H:%M:%S.%f",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%dT%H:%M:%S.%f",
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


def ingest_daily_solar_indices(ctx: FetchContext) -> bool:
    url = "https://services.swpc.noaa.gov/text/daily-solar-indices.txt"
    raw_dir = ctx.data_root / "raw" / "solar"
    raw_dir.mkdir(parents=True, exist_ok=True)
    try:
        raw = fetch_first_ok([url], ctx.timeout, ctx.user_agent).content
    except Exception as exc:  # noqa: BLE001
        log.warning("daily-solar-indices ingest failed: %s", exc)
        return False
    _write_cache(raw_dir / "daily-solar-indices.txt", raw)
    return True


def _parse_daily_solar_indices(raw: str) -> List[Tuple[datetime, float, float]]:
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


def ingest_solar_cycle_indices(ctx: FetchContext) -> bool:
    url = "https://services.swpc.noaa.gov/json/solar-cycle/observed-solar-cycle-indices.json"
    raw_dir = ctx.data_root / "raw" / "solar"
    raw_dir.mkdir(parents=True, exist_ok=True)
    try:
        raw = fetch_first_ok([url], ctx.timeout, ctx.user_agent).content
    except Exception as exc:  # noqa: BLE001
        log.warning("solar cycle indices ingest failed: %s", exc)
        return False
    _write_cache(raw_dir / "observed-solar-cycle-indices.json", raw)
    return True


def _parse_solar_cycle_indices(raw: str) -> List[Tuple[datetime, float, float]]:
    try:
        data = json.loads(raw)
    except Exception:
        return []
    rows: List[Tuple[datetime, float, float]] = []
    if not isinstance(data, list):
        return rows
    for entry in data:
        if not isinstance(entry, dict):
            continue
        time_tag = entry.get("time-tag") or entry.get("time_tag") or entry.get("time") or entry.get("date")
        if not time_tag:
            continue
        dt = None
        for fmt in ("%Y-%m-%d", "%Y-%m"):
            try:
                dt = datetime.strptime(str(time_tag), fmt).replace(tzinfo=timezone.utc)
                break
            except ValueError:
                continue
        if dt is None:
            dt = _parse_time(str(time_tag))
        if dt is None:
            continue
        ssn = entry.get("ssn") or entry.get("sunspot_number") or entry.get("sunspot")
        flux = (
            entry.get("f10.7")
            or entry.get("f107")
            or entry.get("f10_7")
            or entry.get("radio_flux")
            or entry.get("flux")
        )
        if ssn is None or flux is None:
            continue
        try:
            ssn_val = float(ssn)
            flux_val = float(flux)
        except Exception:
            continue
        rows.append((dt, flux_val, ssn_val))
    return rows


def _load_daily_solar_indices(ctx: FetchContext) -> List[Tuple[datetime, float, float]]:
    raw_path = ctx.data_root / "raw" / "solar" / "daily-solar-indices.txt"
    raw = _read_text(raw_path, max_age_seconds=0)
    if raw is None:
        return []
    return _parse_daily_solar_indices(raw)


def _load_solar_cycle_indices(ctx: FetchContext) -> List[Tuple[datetime, float, float]]:
    raw_path = ctx.data_root / "raw" / "solar" / "observed-solar-cycle-indices.json"
    raw = _read_text(raw_path, max_age_seconds=0)
    if raw is None:
        return []
    return _parse_solar_cycle_indices(raw)


def ingest_solar_indices(ctx: FetchContext) -> bool:
    ok = ingest_daily_solar_indices(ctx)
    ok_cycle = ingest_solar_cycle_indices(ctx)
    ok_outlook = ingest_27_day_outlook(ctx)
    return ok or ok_cycle or ok_outlook


def derive_ssn(ctx: FetchContext) -> bool:
    rows = _load_daily_solar_indices(ctx)
    if not rows:
        return False
    entries = _tail(rows, 31)
    output = [f"{dt.year:04d} {dt.month:02d} {dt.day:02d} {ssn:.0f}" for dt, _, ssn in entries]
    target = ctx.data_root / "ssn" / "ssn-31.txt"
    _atomic_write(target, "\n".join(output) + "\n")
    return True


def derive_ssn_history(ctx: FetchContext) -> bool:
    rows = _load_solar_cycle_indices(ctx)
    if not rows:
        rows = _load_daily_solar_indices(ctx)
    if not rows:
        return False
    buckets: Dict[Tuple[int, int], List[float]] = {}
    for dt, _, ssn in rows:
        block = (dt.month - 1) // 2
        buckets.setdefault((dt.year, block), []).append(ssn)
    output: List[str] = []
    for year, block in sorted(buckets):
        values = buckets[(year, block)]
        if values:
            avg = sum(values) / len(values)
            frac = (block * 2) / 12
            year_value = year + frac
            if frac == 0:
                year_label = f"{year}"
            else:
                year_label = f"{year_value:.2f}".rstrip("0").rstrip(".")
            output.append(f"{year_label} {avg:.1f}")
    if not output:
        return False
    target = ctx.data_root / "ssn" / "ssn-history.txt"
    _atomic_write(target, "\n".join(output) + "\n")
    return True


def ingest_27_day_outlook(ctx: FetchContext) -> bool:
    url = "https://services.swpc.noaa.gov/text/27-day-outlook.txt"
    raw_dir = ctx.data_root / "raw" / "solar"
    raw_dir.mkdir(parents=True, exist_ok=True)
    try:
        raw = fetch_first_ok([url], ctx.timeout, ctx.user_agent).content
    except Exception as exc:  # noqa: BLE001
        log.warning("27-day outlook ingest failed: %s", exc)
        return False
    _write_cache(raw_dir / "27-day-outlook.txt", raw)
    return True


def _parse_27_day_outlook(raw: str) -> List[float]:
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


def _load_27_day_outlook(ctx: FetchContext) -> List[float]:
    raw_path = ctx.data_root / "raw" / "solar" / "27-day-outlook.txt"
    raw = _read_text(raw_path, max_age_seconds=0)
    if raw is None:
        return []
    return _parse_27_day_outlook(raw)


def derive_solar_flux(ctx: FetchContext) -> bool:
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


def derive_solar_flux_history(ctx: FetchContext) -> bool:
    rows = _load_solar_cycle_indices(ctx)
    if not rows:
        rows = _load_daily_solar_indices(ctx)
    if not rows:
        return False
    buckets: Dict[Tuple[int, int], List[float]] = {}
    for dt, flux, _ in rows:
        buckets.setdefault((dt.year, dt.month), []).append(flux)
    output: List[str] = []
    for year, month in sorted(buckets):
        values = buckets[(year, month)]
        if values:
            avg = sum(values) / len(values)
            year_value = year + (month - 1) / 12
            output.append(f"{year_value:.2f} {avg:.3f}")
    if not output:
        return False
    target = ctx.data_root / "solar-flux" / "solarflux-history.txt"
    _atomic_write(target, "\n".join(output) + "\n")
    return True


def update_ssn(ctx: FetchContext) -> bool:
    ok = ingest_daily_solar_indices(ctx)
    if not ok:
        log.warning("ssn ingest failed; attempting derive from existing raw")
    return derive_ssn(ctx)


def update_ssn_history(ctx: FetchContext) -> bool:
    ok = ingest_solar_indices(ctx)
    if not ok:
        log.warning("ssn_history ingest failed; attempting derive from existing raw")
    return derive_ssn_history(ctx)


def update_solar_flux(ctx: FetchContext) -> bool:
    ok = ingest_solar_indices(ctx)
    if not ok:
        log.warning("solar_flux ingest failed; attempting derive from existing raw")
    return derive_solar_flux(ctx)


def update_solar_flux_history(ctx: FetchContext) -> bool:
    ok = ingest_solar_indices(ctx)
    if not ok:
        log.warning("solar_flux_history ingest failed; attempting derive from existing raw")
    return derive_solar_flux_history(ctx)


def ingest_kindex(ctx: FetchContext) -> bool:
    url = "https://services.swpc.noaa.gov/products/noaa-planetary-k-index.json"
    forecast_url = "https://services.swpc.noaa.gov/products/noaa-planetary-k-index-forecast.json"
    raw_dir = ctx.data_root / "raw" / "geomag"
    raw_dir.mkdir(parents=True, exist_ok=True)
    ok = False
    try:
        result = fetch_first_ok([url], ctx.timeout, ctx.user_agent)
        _write_cache(raw_dir / "noaa-planetary-k-index.json", result.content)
        ok = True
    except Exception as exc:  # noqa: BLE001
        log.warning("kindex ingest failed: %s", exc)
    try:
        result = fetch_first_ok([forecast_url], ctx.timeout, ctx.user_agent)
        _write_cache(raw_dir / "noaa-planetary-k-index-forecast.json", result.content)
        ok = True
    except Exception as exc:  # noqa: BLE001
        log.warning("kindex forecast ingest failed: %s", exc)
    return ok


def _parse_kindex_rows(raw: str) -> List[Tuple[Optional[datetime], float]]:
    try:
        data = json.loads(raw)
    except Exception:
        return []
    if not isinstance(data, list) or len(data) < 2:
        return []
    header = data[0]
    rows = data[1:]
    kp_index = None
    time_idx = None
    if isinstance(header, list):
        for i, name in enumerate(header):
            lname = str(name).lower()
            if lname in ("kp_index", "kp", "kp_index_3h"):
                kp_index = i
            elif lname in ("time_tag", "time", "time_tag_utc"):
                time_idx = i
    if kp_index is None:
        return []
    values: List[Tuple[Optional[datetime], float]] = []
    for row in rows:
        if not isinstance(row, list) or len(row) <= kp_index:
            continue
        dt = None
        if time_idx is not None and len(row) > time_idx:
            dt = _parse_time(str(row[time_idx]))
        try:
            values.append((dt, float(row[kp_index])))
        except Exception:
            continue
    return values


def derive_kindex(ctx: FetchContext) -> bool:
    raw_path = ctx.data_root / "raw" / "geomag" / "noaa-planetary-k-index.json"
    raw = _read_cache(raw_path, max_age_seconds=0)
    rows: List[Tuple[Optional[datetime], float]] = []
    if raw is not None:
        rows.extend(_parse_kindex_rows(raw))
    forecast_path = ctx.data_root / "raw" / "geomag" / "noaa-planetary-k-index-forecast.json"
    forecast_raw = _read_cache(forecast_path, max_age_seconds=0)
    if forecast_raw is not None:
        rows.extend(_parse_kindex_rows(forecast_raw))

    if not rows:
        return False

    if any(dt is not None for dt, _ in rows):
        rows = [(dt or datetime.min.replace(tzinfo=timezone.utc), val) for dt, val in rows]
        rows.sort(key=lambda item: item[0])

    values = [f"{val:.2f}" for _, val in rows]
    if len(values) < 72 and values:
        values.extend([values[-1]] * (72 - len(values)))
    values = _tail(values, 72)
    if not values:
        return False

    target = ctx.data_root / "geomag" / "kindex.txt"
    _atomic_write(target, "\n".join(values) + "\n")
    return True


def update_kindex(ctx: FetchContext) -> bool:
    ok = ingest_kindex(ctx)
    if not ok:
        log.warning("kindex ingest failed; attempting derive from existing raw")
    return derive_kindex(ctx)


def update_xray(ctx: FetchContext) -> bool:
    ok = ingest_xray(ctx)
    if not ok:
        log.warning("xray ingest failed; attempting to derive from existing raw")
    return derive_xray(ctx)


def ingest_xray(ctx: FetchContext) -> bool:
    url = "https://services.swpc.noaa.gov/json/goes/primary/xrays-7-day.json"
    try:
        result = fetch_first_ok([url], ctx.timeout, ctx.user_agent)
    except Exception as exc:  # noqa: BLE001
        log.warning("xray ingest failed: %s", exc)
        return False
    raw_path = ctx.data_root / "raw" / "xray" / "xrays-7-day.json"
    _write_cache(raw_path, result.content)
    # legacy cache location for backward compatibility
    legacy_path = ctx.data_root / "xray" / "xrays-7-day.json"
    _write_cache(legacy_path, result.content)
    return True


def _load_xray_raw(ctx: FetchContext) -> Optional[list]:
    raw_paths = [
        ctx.data_root / "raw" / "xray" / "xrays-7-day.json",
        ctx.data_root / "xray" / "xrays-7-day.json",
    ]
    raw = None
    for path in raw_paths:
        cached = _read_cache(path, max_age_seconds=0)
        if cached is not None:
            raw = cached
            break
    if raw is None:
        return None
    try:
        data = json.loads(raw)
    except Exception as exc:
        log.warning("xray raw decode failed: %s", exc)
        return None
    if not isinstance(data, list) or not data:
        return None
    return data


def derive_xray(ctx: FetchContext) -> bool:
    data = _load_xray_raw(ctx)
    if data is None:
        log.warning("xray derive missing raw data")
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

    samples: List[Tuple[datetime, float, float]] = []
    for time_tag in set(short_band) | set(long_band):
        dt = _parse_time(time_tag)
        if dt is None:
            continue
        short = short_band.get(time_tag, 1e-9)
        long = long_band.get(time_tag, 1e-9)
        samples.append((dt, short, long))

    samples.sort(key=lambda item: item[0])
    if samples:
        offset = samples[-1][0].minute % 10
        ten_min = [item for item in samples if item[0].minute % 10 == offset]
        if len(ten_min) >= 150:
            samples = ten_min[-150:]
        else:
            samples = samples[-150:]

    lines: List[str] = []
    for dt, short, long in samples:
        hhmm = dt.hour * 100 + dt.minute
        line = (
            f"{dt.year:4d} {dt.month:2d} {dt.day:2d}  {hhmm:04d}"
            f"   00000  00000  {short:11.2e} {long:11.2e}"
        )
        lines.append(line)

    if not lines:
        return False

    target = ctx.data_root / "xray" / "xray.txt"
    _atomic_write(target, "\n".join(lines) + "\n")
    return True


def ingest_solar_wind(ctx: FetchContext) -> bool:
    url = "https://services.swpc.noaa.gov/products/solar-wind/plasma-7-day.json"
    raw_dir = ctx.data_root / "raw" / "solar-wind"
    raw_dir.mkdir(parents=True, exist_ok=True)
    try:
        result = fetch_first_ok([url], ctx.timeout, ctx.user_agent)
    except Exception as exc:  # noqa: BLE001
        log.warning("solar wind ingest failed: %s", exc)
        return False
    _write_cache(raw_dir / "plasma-7-day.json", result.content)
    return True


def derive_solar_wind(ctx: FetchContext) -> bool:
    raw_path = ctx.data_root / "raw" / "solar-wind" / "plasma-7-day.json"
    raw = _read_cache(raw_path, max_age_seconds=0)
    if raw is None:
        return False
    try:
        data = json.loads(raw)
    except Exception as exc:  # noqa: BLE001
        log.warning("solar wind decode failed: %s", exc)
        return False
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

    max_dt: Optional[datetime] = None
    for row in rows:
        if not isinstance(row, list) or len(row) <= time_idx:
            continue
        dt = _parse_time(str(row[time_idx]))
        if dt is None:
            continue
        if max_dt is None or dt > max_dt:
            max_dt = dt
    if max_dt is None:
        return False
    cutoff = max_dt - timedelta(hours=24)
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


def update_solar_wind(ctx: FetchContext) -> bool:
    ok = ingest_solar_wind(ctx)
    if not ok:
        log.warning("solar_wind ingest failed; attempting derive from existing raw")
    return derive_solar_wind(ctx)


def ingest_bz(ctx: FetchContext) -> bool:
    url = "https://services.swpc.noaa.gov/products/solar-wind/mag-7-day.json"
    raw_dir = ctx.data_root / "raw" / "solar-wind"
    raw_dir.mkdir(parents=True, exist_ok=True)
    try:
        result = fetch_first_ok([url], ctx.timeout, ctx.user_agent)
    except Exception as exc:  # noqa: BLE001
        log.warning("bz ingest failed: %s", exc)
        return False
    _write_cache(raw_dir / "mag-7-day.json", result.content)
    return True


def derive_bz(ctx: FetchContext) -> bool:
    raw_path = ctx.data_root / "raw" / "solar-wind" / "mag-7-day.json"
    raw = _read_cache(raw_path, max_age_seconds=0)
    if raw is None:
        return False
    try:
        data = json.loads(raw)
    except Exception as exc:  # noqa: BLE001
        log.warning("bz decode failed: %s", exc)
        return False
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

    buckets: Dict[int, Tuple[int, float, float, float, float]] = {}
    for row in rows:
        if not isinstance(row, list) or len(row) <= max(time_idx, bx_idx, by_idx, bz_idx, bt_idx):
            continue
        dt = _parse_time(str(row[time_idx]))
        if dt is None:
            continue
        try:
            bx = float(row[bx_idx])
            by = float(row[by_idx])
            bz = float(row[bz_idx])
            bt = float(row[bt_idx])
        except Exception:
            continue
        ts = int(dt.timestamp())
        bucket = ts - (ts % 600)
        prev = buckets.get(bucket)
        if prev is None or ts >= prev[0]:
            buckets[bucket] = (ts, bx, by, bz, bt)

    points = sorted(buckets.values(), key=lambda item: item[0])
    if not points:
        return False
    if len(points) > 150:
        points = points[-150:]

    lines: List[str] = ["# UNIX        Bx     By     Bz     Bt"]
    for ts, bx, by, bz, bt in points:
        lines.append(f"{ts} {bx:6.1f} {by:6.1f} {bz:6.1f} {bt:6.1f}")

    target = ctx.data_root / "Bz" / "Bz.txt"
    _atomic_write(target, "\n".join(lines) + "\n")
    return True


def update_bz(ctx: FetchContext) -> bool:
    ok = ingest_bz(ctx)
    if not ok:
        log.warning("bz ingest failed; attempting derive from existing raw")
    return derive_bz(ctx)


def ingest_noaa_scales(ctx: FetchContext) -> bool:
    url = "https://services.swpc.noaa.gov/products/noaa-scales.json"
    raw_dir = ctx.data_root / "raw" / "NOAASpaceWX"
    raw_dir.mkdir(parents=True, exist_ok=True)
    try:
        result = fetch_first_ok([url], ctx.timeout, ctx.user_agent)
    except Exception as exc:  # noqa: BLE001
        log.warning("noaa scales ingest failed: %s", exc)
        return False
    _write_cache(raw_dir / "noaa-scales.json", result.content)
    return True


def derive_noaa_scales(ctx: FetchContext) -> bool:
    raw_path = ctx.data_root / "raw" / "NOAASpaceWX" / "noaa-scales.json"
    raw = _read_cache(raw_path, max_age_seconds=0)
    if raw is None:
        return False
    try:
        data = json.loads(raw)
    except Exception as exc:  # noqa: BLE001
        log.warning("noaa scales decode failed: %s", exc)
        return False
    if not isinstance(data, dict):
        return False

    def _extract(scale_key: str) -> List[int]:
        values = data.get(scale_key, {})
        if isinstance(values, dict):
            forecast = values.get("forecast", [])
            if isinstance(forecast, list) and forecast:
                output: List[int] = []
                for item in forecast[:4]:
                    if not isinstance(item, dict):
                        output.append(0)
                        continue
                    scale = item.get("scale")
                    try:
                        output.append(int(scale or 0))
                    except Exception:
                        output.append(0)
                return output
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


def update_noaa_scales(ctx: FetchContext) -> bool:
    ok = ingest_noaa_scales(ctx)
    if not ok:
        log.warning("noaa_scales ingest failed; attempting derive from existing raw")
    return derive_noaa_scales(ctx)


def update_aurora(ctx: FetchContext) -> bool:
    ok = ingest_aurora(ctx)
    if not ok:
        log.warning("aurora ingest failed; attempting to derive from existing raw")
    return derive_aurora(ctx)


def _get_key_ci(obj: Dict, names: List[str]):
    lookup = {str(k).lower().replace("_", " ").strip(): k for k in obj.keys()}
    for name in names:
        key = lookup.get(name.lower().replace("_", " ").strip())
        if key is not None:
            return obj.get(key)
    return None


def _parse_aurora_forecast_list(data_obj) -> List[Tuple[int, float]]:
    parsed: List[Tuple[int, float]] = []
    if not isinstance(data_obj, list) or not data_obj:
        return parsed
    header = data_obj[0]
    rows = data_obj[1:]
    time_idx = 0
    value_idx = 1
    if isinstance(header, list) and header and all(isinstance(x, str) for x in header):
        for i, name in enumerate(header):
            lname = name.lower()
            if "time" in lname:
                time_idx = i
            if "forecast" in lname or "value" in lname or "kp" in lname:
                value_idx = i
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
        parsed.append((int(dt.timestamp()), value))
    return parsed


def _parse_aurora_hemi_power(raw_text: str) -> List[Tuple[int, float]]:
    parsed: List[Tuple[int, float]] = []
    normalized = raw_text.replace("\r", "\n")
    for line in normalized.splitlines():
        line = line.strip()
        if not line or not line[0].isdigit():
            continue
        parts = line.split()
        if len(parts) >= 4 and ("_" in parts[0] or "T" in parts[0]):
            dt = None
            for fmt in ("%Y-%m-%d_%H:%M", "%Y-%m-%d_%H:%M:%S"):
                try:
                    dt = datetime.strptime(parts[0], fmt).replace(tzinfo=timezone.utc)
                    break
                except ValueError:
                    continue
            if dt is None:
                dt = _parse_time(parts[0].replace("_", "T"))
            if dt is not None:
                values: List[float] = []
                for token in parts[2:]:
                    try:
                        values.append(float(token))
                    except Exception:
                        continue
                if values:
                    parsed.append((int(dt.timestamp()), max(values)))
                    continue
        dt = None
        rest = ""
        match = re.match(
            r"(\d{4})[-/](\d{1,2})[-/](\d{1,2})[ T_]+(\d{2}):?(\d{2})(?::?(\d{2}))?",
            line,
        )
        if match:
            year, month, day, hour, minute, second = match.groups()
            dt = datetime(
                int(year),
                int(month),
                int(day),
                int(hour),
                int(minute),
                int(second or 0),
                tzinfo=timezone.utc,
            )
            rest = line[match.end() :]
        else:
            match = re.match(r"(\d{4})\s+(\d{1,2})\s+(\d{1,2})\s+(\d{4})", line)
            if match:
                year, month, day, hhmm = match.groups()
                hour = int(hhmm[:2])
                minute = int(hhmm[2:])
                dt = datetime(int(year), int(month), int(day), hour, minute, tzinfo=timezone.utc)
                rest = line[match.end() :]
        if dt is None:
            continue
        values = [
            float(val)
            for val in re.findall(r"[-+]?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?", rest)
        ]
        if not values:
            continue
        parsed.append((int(dt.timestamp()), max(values)))
    return parsed


def ingest_aurora(ctx: FetchContext) -> bool:
    hemi_power_url = "https://services.swpc.noaa.gov/text/aurora-nowcast-hemi-power.txt"
    forecast_url = "https://services.swpc.noaa.gov/products/aurora-30-minute-forecast.json"
    ovation_url = "https://services.swpc.noaa.gov/json/ovation_aurora_latest.json"
    raw_dir = ctx.data_root / "raw" / "aurora"
    raw_dir.mkdir(parents=True, exist_ok=True)

    try:
        result = fetch_first_ok([hemi_power_url], ctx.timeout, ctx.user_agent)
        (raw_dir / "hemi-power.txt").write_bytes(result.content)
        (raw_dir / "source.txt").write_text("hemi_power", encoding="utf-8")
        return True
    except Exception as exc:  # noqa: BLE001
        log.warning("aurora hemi-power ingest failed: %s", exc)

    data = _load_json([forecast_url], ctx)
    if data is not None:
        try:
            (raw_dir / "forecast.json").write_text(json.dumps(data), encoding="utf-8")
            (raw_dir / "source.txt").write_text("forecast", encoding="utf-8")
            return True
        except Exception:  # noqa: BLE001
            pass

    data = _load_json([ovation_url], ctx)
    if data is not None:
        try:
            (raw_dir / "ovation.json").write_text(json.dumps(data), encoding="utf-8")
            (raw_dir / "source.txt").write_text("ovation", encoding="utf-8")
            return True
        except Exception:  # noqa: BLE001
            return False
    return False


def _load_aurora_source(ctx: FetchContext) -> Tuple[Optional[str], Optional[bytes]]:
    raw_dir = ctx.data_root / "raw" / "aurora"
    source_path = raw_dir / "source.txt"
    source = None
    if source_path.exists():
        source = source_path.read_text(encoding="utf-8", errors="replace").strip()
    if source == "hemi_power":
        path = raw_dir / "hemi-power.txt"
        if path.exists():
            return source, path.read_bytes()
    if source == "forecast":
        path = raw_dir / "forecast.json"
        if path.exists():
            return source, path.read_bytes()
    if source == "ovation":
        path = raw_dir / "ovation.json"
        if path.exists():
            return source, path.read_bytes()

    for fallback in ("hemi-power.txt", "forecast.json", "ovation.json"):
        path = raw_dir / fallback
        if path.exists():
            content = path.read_bytes()
            if fallback.endswith(".txt"):
                return "hemi_power", content
            if fallback.startswith("forecast"):
                return "forecast", content
            return "ovation", content
    return None, None


def derive_aurora(ctx: FetchContext) -> bool:
    source, raw = _load_aurora_source(ctx)
    if not source or raw is None:
        log.warning("aurora derive missing raw data")
        return False

    points: List[Tuple[int, float]] = []
    if source == "hemi_power":
        points = _parse_aurora_hemi_power(raw.decode("utf-8", errors="replace"))
    elif source == "forecast":
        try:
            data = json.loads(raw)
        except Exception as exc:
            log.warning("aurora forecast decode failed: %s", exc)
            data = None
        points = _parse_aurora_forecast_list(data)
    elif source == "ovation":
        try:
            data = json.loads(raw)
        except Exception as exc:
            log.warning("aurora ovation decode failed: %s", exc)
            data = None
        if isinstance(data, dict):
            coords = _get_key_ci(data, ["coordinates", "data", "coords"])
            time_tag = _get_key_ci(data, ["observation time", "forecast time", "time_tag", "time"])
            dt = _parse_time(str(time_tag)) if time_tag else None
            if isinstance(coords, list):
                values = []
                for item in coords:
                    if isinstance(item, list) and len(item) >= 3:
                        try:
                            values.append(float(item[-1]))
                        except Exception:
                            continue
                if values:
                    ts = int((dt or datetime.now(timezone.utc)).timestamp())
                    points.append((ts, max(values)))

    if not points:
        log.warning("aurora derive yielded no points from %s", source)
        return False

    if source == "ovation" and len(points) == 1:
        target = ctx.data_root / "aurora" / "aurora.txt"
        existing: List[Tuple[int, float]] = []
        if target.exists():
            try:
                for line in target.read_text(encoding="utf-8").splitlines():
                    parts = line.split()
                    if len(parts) >= 2:
                        existing.append((int(parts[0]), float(parts[1])))
            except Exception:
                existing = []
        ts_new, value = points[0]
        if existing and existing[-1][0] == ts_new:
            existing[-1] = (ts_new, value)
        else:
            existing.append((ts_new, value))
        points = existing

    now_ts = int(datetime.now(timezone.utc).timestamp())
    unique: Dict[int, float] = {}
    for ts, pct in points:
        if ts <= now_ts:
            unique[ts] = pct
    points = sorted(unique.items(), key=lambda item: item[0])
    if not points:
        return False

    if len(points) > 100:
        buckets: Dict[int, Tuple[int, float]] = {}
        for ts, pct in points:
            bucket = ts - (ts % 1800)
            prev = buckets.get(bucket)
            if prev is None or ts >= prev[0]:
                buckets[bucket] = (ts, pct)
        points = sorted(buckets.values(), key=lambda item: item[0])

    if len(points) < 48:
        if source == "ovation" and len(points) > 1:
            first_ts, first_pct = points[0]
            missing = 48 - len(points)
            padded = []
            for i in range(missing, 0, -1):
                ts = first_ts - i * 1800
                padded.append((ts, first_pct))
            points = padded + points
        else:
            latest_ts, latest_pct = points[-1]
            synthesized = []
            for i in range(48):
                ts = latest_ts - (47 - i) * 1800
                synthesized.append((ts, latest_pct))
            points = synthesized
    elif len(points) > 48:
        points = points[-48:]

    lines = [f"{ts} {pct:.0f}" for ts, pct in points]

    target = ctx.data_root / "aurora" / "aurora.txt"
    _atomic_write(target, "\n".join(lines) + "\n")
    return True


def ingest_dst(ctx: FetchContext) -> bool:
    url = "https://services.swpc.noaa.gov/products/kyoto-dst.json"
    raw_dir = ctx.data_root / "raw" / "dst"
    raw_dir.mkdir(parents=True, exist_ok=True)
    try:
        result = fetch_first_ok([url], ctx.timeout, ctx.user_agent)
    except Exception as exc:  # noqa: BLE001
        log.warning("dst ingest failed: %s", exc)
        return False
    _write_cache(raw_dir / "kyoto-dst.json", result.content)
    return True


def derive_dst(ctx: FetchContext) -> bool:
    raw_path = ctx.data_root / "raw" / "dst" / "kyoto-dst.json"
    raw = _read_cache(raw_path, max_age_seconds=0)
    if raw is None:
        return False
    try:
        data = json.loads(raw)
    except Exception as exc:  # noqa: BLE001
        log.warning("dst decode failed: %s", exc)
        return False
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
    def _parse_iso(line: str) -> Optional[datetime]:
        try:
            return datetime.strptime(line.split()[0], "%Y-%m-%dT%H:%M:%S").replace(tzinfo=timezone.utc)
        except Exception:
            return None
    stamped: List[Tuple[datetime, str]] = []
    for line in lines:
        dt = _parse_iso(line)
        if dt:
            stamped.append((dt, line))
    if stamped:
        stamped.sort(key=lambda item: item[0])
        lines = [line for _, line in stamped[-24:]]
    target = ctx.data_root / "dst" / "dst.txt"
    _atomic_write(target, "\n".join(lines) + "\n")
    return True


def update_dst(ctx: FetchContext) -> bool:
    ok = ingest_dst(ctx)
    if not ok:
        log.warning("dst ingest failed; attempting derive from existing raw")
    return derive_dst(ctx)


def _flatten_values(obj) -> List[float]:
    values: List[float] = []
    if isinstance(obj, list):
        for item in obj:
            values.extend(_flatten_values(item))
    elif isinstance(obj, (int, float)):
        values.append(float(obj))
    return values


def ingest_drap(ctx: FetchContext) -> bool:
    url = "https://services.swpc.noaa.gov/products/animations/d-rap/global.json"
    raw_dir = ctx.data_root / "raw" / "drap"
    raw_dir.mkdir(parents=True, exist_ok=True)
    try:
        result = fetch_first_ok([url], ctx.timeout, ctx.user_agent)
    except Exception as exc:  # noqa: BLE001
        log.warning("drap ingest failed: %s", exc)
        return False
    _write_cache(raw_dir / "global.json", result.content)
    return True


def derive_drap(ctx: FetchContext) -> bool:
    raw_path = ctx.data_root / "raw" / "drap" / "global.json"
    raw = _read_cache(raw_path, max_age_seconds=0)
    if raw is None:
        return False
    try:
        data = json.loads(raw)
    except Exception as exc:  # noqa: BLE001
        log.warning("drap decode failed: %s", exc)
        return False
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


def update_drap(ctx: FetchContext) -> bool:
    ok = ingest_drap(ctx)
    if not ok:
        log.warning("drap ingest failed; attempting derive from existing raw")
    return derive_drap(ctx)


PHASE2_JOBS = [
    {"id": "update_ssn", "func": update_ssn, "trigger": "interval", "hours": 1, "replace_existing": True},
    {"id": "update_ssn_history", "func": update_ssn_history, "trigger": "interval", "hours": 24, "replace_existing": True},
    {"id": "update_solar_flux", "func": update_solar_flux, "trigger": "interval", "hours": 1, "replace_existing": True},
    {"id": "update_solar_flux_history", "func": update_solar_flux_history, "trigger": "interval", "hours": 24, "replace_existing": True},
    {"id": "update_kindex", "func": update_kindex, "trigger": "interval", "hours": 1, "replace_existing": True},
    {"id": "update_xray", "func": update_xray, "trigger": "interval", "minutes": 1, "replace_existing": True},
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
