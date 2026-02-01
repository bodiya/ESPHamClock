from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Iterable, List, Optional
from xml.etree import ElementTree

from .http import fetch_first_ok
from .phase1 import FetchContext


log = logging.getLogger("hamclock-backend.fetchers.phase3")


def _atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(content, encoding="utf-8")
    tmp.replace(path)


def _parse_time(value: str) -> Optional[datetime]:
    for fmt in (
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%dT%H:%M:%SZ",
        "%a, %d %b %Y %H:%M:%S %z",
        "%a, %d %b %Y %H:%M:%S %Z",
    ):
        try:
            dt = datetime.strptime(value, fmt)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.astimezone(timezone.utc)
        except ValueError:
            continue
    return None


def _coerce_freq_hz(value: Optional[object]) -> Optional[int]:
    if value is None:
        return None
    try:
        freq = float(value)
    except Exception:
        return None
    if freq < 1000:
        return int(freq * 1_000_000)
    if freq < 100_000:
        return int(freq * 1000)
    return int(freq)


def ingest_onta(ctx: FetchContext) -> bool:
    url = "https://api.pota.app/spot/activator"
    raw_dir = ctx.data_root / "raw" / "onta"
    raw_dir.mkdir(parents=True, exist_ok=True)
    try:
        data = fetch_first_ok([url], ctx.timeout, ctx.user_agent).content
    except Exception as exc:  # noqa: BLE001
        log.warning("POTA ingest failed: %s", exc)
        return False
    (raw_dir / "activator.json").write_bytes(data)
    return True


def derive_onta(ctx: FetchContext) -> bool:
    raw_path = ctx.data_root / "raw" / "onta" / "activator.json"
    if not raw_path.exists():
        return False
    try:
        spots = __import__("json").loads(raw_path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        log.warning("POTA JSON decode failed: %s", exc)
        return False

    if not isinstance(spots, list):
        return False

    lines = ["#call,Hz,unix,mode,grid,lat,lng,park,org"]
    for spot in spots:
        if not isinstance(spot, dict):
            continue
        call = spot.get("activator") or spot.get("activatorCallsign") or spot.get("call") or spot.get("callsign")
        freq_hz = _coerce_freq_hz(spot.get("frequency") or spot.get("freq") or spot.get("frequency_mhz"))
        mode = spot.get("mode") or ""
        grid = spot.get("grid") or spot.get("grid6") or ""
        lat = spot.get("latitude") or spot.get("lat")
        lng = spot.get("longitude") or spot.get("lon") or spot.get("lng")
        park = spot.get("reference") or spot.get("park") or spot.get("locationDesc") or ""
        time_tag = spot.get("spotTime") or spot.get("timestamp") or spot.get("time")
        dt = _parse_time(str(time_tag)) if time_tag else None
        if dt is None and isinstance(time_tag, (int, float)):
            dt = datetime.fromtimestamp(float(time_tag), tz=timezone.utc)

        if not call or freq_hz is None or dt is None or lat is None or lng is None:
            continue
        try:
            lat_f = float(lat)
            lng_f = float(lng)
        except Exception:
            continue

        lines.append(
            f"{call},{freq_hz},{int(dt.timestamp())},{mode},{grid},{lat_f:.4f},{lng_f:.4f},{park},POTA"
        )

    if len(lines) <= 1:
        return False

    target = ctx.data_root / "ONTA" / "onta.txt"
    _atomic_write(target, "\n".join(lines) + "\n")
    return True


def _parse_rss_titles(xml_text: str) -> List[Dict[str, str]]:
    items: List[Dict[str, str]] = []
    try:
        root = ElementTree.fromstring(xml_text)
    except ElementTree.ParseError:
        return items

    channel = root.find("channel") if root is not None else None
    source_title = ""
    if channel is not None:
        title_el = channel.find("title")
        if title_el is not None and title_el.text:
            source_title = title_el.text.strip()

    for item in root.findall(".//item"):
        title_el = item.find("title")
        if title_el is None or not title_el.text:
            continue
        items.append({"source": source_title, "title": title_el.text.strip()})
    return items


def ingest_rss(ctx: FetchContext) -> bool:
    feeds = ctx.rss_feeds or []
    raw_dir = ctx.data_root / "raw" / "rss"
    raw_dir.mkdir(parents=True, exist_ok=True)
    if not feeds:
        return False
    ok = False
    for idx, url in enumerate(feeds):
        try:
            raw = fetch_first_ok([url], ctx.timeout, ctx.user_agent).content
        except Exception as exc:  # noqa: BLE001
            log.warning("RSS ingest failed for %s: %s", url, exc)
            continue
        (raw_dir / f"feed-{idx}.xml").write_bytes(raw)
        ok = True
    (raw_dir / "feeds.json").write_text(__import__("json").dumps(feeds), encoding="utf-8")
    return ok


def derive_rss(ctx: FetchContext) -> bool:
    raw_dir = ctx.data_root / "raw" / "rss"
    feeds_path = raw_dir / "feeds.json"
    if not feeds_path.exists():
        return False
    try:
        feeds = __import__("json").loads(feeds_path.read_text(encoding="utf-8"))
    except Exception:
        feeds = ctx.rss_feeds or []

    headlines: List[str] = []
    seen = set()

    for idx, url in enumerate(feeds):
        feed_path = raw_dir / f"feed-{idx}.xml"
        if not feed_path.exists():
            continue
        raw = feed_path.read_text(encoding="utf-8", errors="replace")
        items = _parse_rss_titles(raw)

        for item in items:
            source = item.get("source") or url
            title = item.get("title")
            if not title:
                continue
            line = f"{source}: {title}"
            if line in seen:
                continue
            seen.add(line)
            headlines.append(line)
            if len(headlines) >= 15:
                break
        if len(headlines) >= 15:
            break

    if not headlines:
        return False

    target = ctx.data_root / "RSS" / "web15rss.txt"
    _atomic_write(target, "\n".join(headlines) + "\n")
    return True


def update_onta(ctx: FetchContext) -> bool:
    ok = ingest_onta(ctx)
    if not ok:
        log.warning("onta ingest failed; attempting derive from existing raw")
    return derive_onta(ctx)


def update_rss(ctx: FetchContext) -> bool:
    ok = ingest_rss(ctx)
    if not ok:
        log.warning("rss ingest failed; attempting derive from existing raw")
    return derive_rss(ctx)


PHASE3_JOBS = [
    {"id": "update_onta", "func": update_onta, "trigger": "interval", "minutes": 5, "replace_existing": True},
    {"id": "update_rss", "func": update_rss, "trigger": "interval", "hours": 1, "replace_existing": True},
]


def run_phase3(ctx: FetchContext) -> None:
    for job in PHASE3_JOBS:
        job_name = job.get("id", "phase3")
        func = job["func"]
        try:
            ok = func(ctx)
            log.info("Phase3 job %s completed: %s", job_name, ok)
        except Exception as exc:  # noqa: BLE001
            log.warning("Phase3 job %s failed: %s", job_name, exc)
