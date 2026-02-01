from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from .http import fetch_first_ok
from .phase1 import FetchContext


log = logging.getLogger("hamclock-backend.fetchers.phase4")


def _atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(content, encoding="utf-8")
    tmp.replace(path)


def _read_cache(path: Path, max_age_seconds: float) -> Optional[str]:
    if not path.exists():
        return None
    if max_age_seconds > 0:
        age = (datetime.now(timezone.utc) - datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)).total_seconds()
        if age > max_age_seconds:
            return None
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _write_cache(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(content, encoding="utf-8")
    tmp.replace(path)


def _reverse_geocode(ctx: FetchContext, lat: float, lng: float) -> Optional[str]:
    cache_root = ctx.data_root / "geocode"
    key = f"{lat:.3f},{lng:.3f}"
    cache_path = cache_root / f"{key}.txt"
    cached = _read_cache(cache_path, max_age_seconds=ctx.geocode_cache_days * 86400)
    if cached:
        return cached

    if ctx.geocode_provider == "nominatim":
        params = [
            f"format=jsonv2",
            f"lat={lat}",
            f"lon={lng}",
            "zoom=10",
            "addressdetails=1",
        ]
        if ctx.geocode_email:
            params.append(f"email={ctx.geocode_email}")
        url = f"{ctx.geocode_base_url}?{'&'.join(params)}"
        data = fetch_first_ok([url], ctx.timeout, ctx.user_agent).content
        try:
            payload = __import__("json").loads(data)
        except Exception as exc:  # noqa: BLE001
            log.warning("Reverse geocode JSON decode failed: %s", exc)
            return None
        address = payload.get("address") or {}
        name = address.get("city") or address.get("town") or address.get("village") or address.get("hamlet")
        admin1 = address.get("state") or address.get("region") or address.get("county")
        country = address.get("country")
        parts = [p for p in (name, admin1, country) if p]
        if not parts:
            return None
        city = ", ".join(parts)
    else:
        return None

    _write_cache(cache_path, city)
    return city


def _wind_dir_name(deg: float) -> str:
    dirs = ["N", "NE", "E", "SE", "S", "SW", "W", "NW"]
    idx = int((deg + 22.5) // 45) % 8
    return dirs[idx]


def _map_weather_code(code: Optional[int]) -> Tuple[str, str]:
    if code is None:
        return "Unknown", "Unknown"
    # Open-Meteo codes: https://open-meteo.com/en/docs
    if code == 0:
        return "Clear", "Clear"
    if code in (1, 2, 3):
        return "Clouds", "Clouds"
    if code in (45, 48):
        return "Fog", "Fog"
    if code in (51, 53, 55, 56, 57):
        return "Drizzle", "Drizzle"
    if code in (61, 63, 65, 66, 67):
        return "Rain", "Rain"
    if code in (71, 73, 75, 77):
        return "Snow", "Snow"
    if code in (80, 81, 82):
        return "Rain", "Rain"
    if code in (85, 86):
        return "Snow", "Snow"
    if code in (95, 96, 99):
        return "Thunderstorm", "Thunderstorm"
    return "Unknown", "Unknown"


def _fetch_open_meteo_current(lat: float, lng: float, timeout: float, user_agent: str) -> Optional[Dict[str, float]]:
    url = (
        "https://api.open-meteo.com/v1/forecast"
        f"?latitude={lat}&longitude={lng}"
        "&current_weather=true&hourly=relativehumidity_2m,pressure_msl,cloudcover"
        "&timezone=auto"
    )
    data = fetch_first_ok([url], timeout, user_agent).content
    try:
        payload = __import__("json").loads(data)
    except Exception as exc:  # noqa: BLE001
        log.warning("Open-Meteo JSON decode failed: %s", exc)
        return None

    current = payload.get("current_weather") or {}
    hourly = payload.get("hourly") or {}
    times = hourly.get("time") or []
    if current and times:
        try:
            idx = times.index(current.get("time"))
        except Exception:
            idx = -1
    else:
        idx = -1

    humidity = None
    pressure = None
    cloudcover = None
    if idx >= 0:
        humidity_vals = hourly.get("relativehumidity_2m") or []
        pressure_vals = hourly.get("pressure_msl") or []
        cloud_vals = hourly.get("cloudcover") or []
        if idx < len(humidity_vals):
            humidity = humidity_vals[idx]
        if idx < len(pressure_vals):
            pressure = pressure_vals[idx]
        if idx < len(cloud_vals):
            cloudcover = cloud_vals[idx]

    return {
        "temperature_c": current.get("temperature"),
        "wind_speed_mps": current.get("windspeed") and float(current.get("windspeed")) / 3.6,
        "wind_dir_deg": current.get("winddirection"),
        "weather_code": current.get("weathercode"),
        "humidity_percent": humidity,
        "pressure_hpa": pressure,
        "cloudcover": cloudcover,
        "time": current.get("time"),
        "timezone_offset": payload.get("utc_offset_seconds", 0),
    }


def update_wx(ctx: FetchContext, is_de: bool, lat: float, lng: float) -> Optional[str]:
    data = _fetch_open_meteo_current(lat, lng, ctx.timeout, ctx.user_agent)
    if not data:
        return None

    city = _reverse_geocode(ctx, lat, lng) or "Unknown"
    wind_dir = data.get("wind_dir_deg") or 0.0
    wind_name = _wind_dir_name(float(wind_dir))
    clouds, conditions = _map_weather_code(int(data.get("weather_code")) if data.get("weather_code") is not None else None)
    pressure = data.get("pressure_hpa")
    humidity = data.get("humidity_percent")

    lines = [
        f"city={city}",
        f"temperature_c={int(round(float(data.get('temperature_c') or 0)))}",
        f"pressure_hPa={int(round(float(pressure)))}" if pressure is not None else "pressure_hPa=0",
        "pressure_chg=-999",
        f"humidity_percent={int(round(float(humidity)))}" if humidity is not None else "humidity_percent=0",
        f"wind_speed_mps={float(data.get('wind_speed_mps') or 0):.2f}",
        f"wind_dir_name={wind_name}",
        f"clouds={clouds}",
        f"conditions={conditions}",
        "attribution=open-meteo.com",
        f"timezone={int(data.get('timezone_offset') or 0)}",
    ]
    return "\n".join(lines) + "\n"


def ingest_worldwx(ctx: FetchContext) -> bool:
    lats = list(range(-90, 91, 4))
    lngs = list(range(-180, 181, 5))
    raw_dir = ctx.data_root / "raw" / "worldwx"
    raw_dir.mkdir(parents=True, exist_ok=True)

    ok = False
    for lng in lngs:
        lat_values = ",".join(str(lat) for lat in lats)
        lng_values = ",".join([str(lng)] * len(lats))
        url = (
            "https://api.open-meteo.com/v1/forecast"
            f"?latitude={lat_values}&longitude={lng_values}"
            "&current_weather=true&hourly=relativehumidity_2m,pressure_msl"
            "&timezone=UTC"
        )
        try:
            data = fetch_first_ok([url], ctx.timeout, ctx.user_agent).content
        except Exception as exc:  # noqa: BLE001
            log.warning("Open-Meteo grid fetch failed: %s", exc)
            continue
        (raw_dir / f"{lng}.json").write_bytes(data)
        ok = True

    if ok:
        meta = {"lats": lats, "lngs": lngs, "generated": datetime.now(timezone.utc).isoformat()}
        (raw_dir / "index.json").write_text(__import__("json").dumps(meta), encoding="utf-8")
    return ok


def derive_worldwx(ctx: FetchContext) -> bool:
    raw_dir = ctx.data_root / "raw" / "worldwx"
    index_path = raw_dir / "index.json"
    if not index_path.exists():
        return False
    try:
        meta = __import__("json").loads(index_path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        log.warning("Open-Meteo index decode failed: %s", exc)
        return False
    lats = meta.get("lats") or list(range(-90, 91, 4))
    lngs = meta.get("lngs") or list(range(-180, 181, 5))

    rows: List[str] = ["#   lat     lng  temp,C     %hum    mps     dir    mmHg    Wx           TZ"]
    count = 0

    for lng in lngs:
        raw_path = raw_dir / f"{lng}.json"
        if not raw_path.exists():
            continue
        try:
            payload = __import__("json").loads(raw_path.read_text(encoding="utf-8"))
        except Exception as exc:  # noqa: BLE001
            log.warning("Open-Meteo grid JSON decode failed: %s", exc)
            continue

        if isinstance(payload, list):
            entries = payload
        else:
            entries = [payload]

        for idx, entry in enumerate(entries):
            if not isinstance(entry, dict) or idx >= len(lats):
                continue
            current = entry.get("current_weather") or {}
            hourly = entry.get("hourly") or {}
            times = hourly.get("time") or []
            humid = hourly.get("relativehumidity_2m") or []
            pressure = hourly.get("pressure_msl") or []

            if not isinstance(current, dict):
                continue
            time_tag = current.get("time")
            try:
                t_idx = times.index(time_tag) if time_tag in times else -1
            except Exception:
                t_idx = -1
            humidity = humid[t_idx] if 0 <= t_idx < len(humid) else 0
            press = pressure[t_idx] if 0 <= t_idx < len(pressure) else 0
            temp = current.get("temperature") or 0.0
            wind_speed = (current.get("windspeed") or 0.0) / 3.6
            wind_dir = current.get("winddirection") or 0.0
            code = current.get("weathercode")
            wx, _ = _map_weather_code(int(code) if code is not None else None)
            tz = int(round(lng / 15.0)) * 3600
            lat = lats[idx]
            rows.append(
                f"{lat:6d} {lng:7d} {temp:7.1f} {humidity:7.1f} {wind_speed:7.1f} {wind_dir:7.1f} {press:7.1f} {wx:<15} {tz:d}"
            )
            count += 1

    if count == 0:
        return False
    target = ctx.data_root / "worldwx" / "wx.txt"
    _atomic_write(target, "\n".join(rows) + "\n")
    return True


def update_worldwx(ctx: FetchContext) -> bool:
    ok = ingest_worldwx(ctx)
    if not ok:
        log.warning("worldwx ingest failed; attempting derive from existing raw")
    return derive_worldwx(ctx)


PHASE4_JOBS = [
    {"id": "update_worldwx", "func": update_worldwx, "trigger": "interval", "minutes": 45, "replace_existing": True},
]


def run_phase4(ctx: FetchContext) -> None:
    for job in PHASE4_JOBS:
        job_name = job.get("id", "phase4")
        func = job["func"]
        try:
            ok = func(ctx)
            log.info("Phase4 job %s completed: %s", job_name, ok)
        except Exception as exc:  # noqa: BLE001
            log.warning("Phase4 job %s failed: %s", job_name, exc)
