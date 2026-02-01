from __future__ import annotations

import hashlib
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Optional
from xml.etree import ElementTree

import requests


log = logging.getLogger("hamclock-backend.spots")


def _cache_paths(root: Path, kind: str, key: str) -> Path:
    digest = hashlib.sha1(key.encode("utf-8")).hexdigest()
    return root / "spots_cache" / kind / f"{digest}.txt"


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


def _coerce_freq_hz(value: Optional[str]) -> Optional[int]:
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


def _parse_time_attr(value: Optional[str]) -> Optional[int]:
    if not value:
        return None
    if value.isdigit():
        return int(value)
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M:%SZ"):
        try:
            dt = datetime.strptime(value, fmt).replace(tzinfo=timezone.utc)
            return int(dt.timestamp())
        except ValueError:
            continue
    return None


def fetch_pskreporter(
    *,
    data_root: Path,
    user_agent: str,
    timeout: float,
    max_age: int,
    query_type: str,
    query_value: str,
) -> Optional[str]:
    params: Dict[str, str] = {
        "flowStartSeconds": f"-{max_age}",
        "rronly": "1",
    }
    if query_type == "bygrid":
        params["receiverLocator"] = query_value
    elif query_type == "ofgrid":
        params["senderLocator"] = query_value
    elif query_type == "bycall":
        params["receiverCallsign"] = query_value
    elif query_type == "ofcall":
        params["senderCallsign"] = query_value
    else:
        return None

    cache_key = f"psk:{query_type}:{query_value}:{max_age}"
    cache_path = _cache_paths(data_root, "psk", cache_key)
    cached = _read_cache(cache_path, max_age_seconds=max_age)
    if cached:
        return cached

    url = "https://pskreporter.info/cgi-bin/pskquery5.pl"
    resp = requests.get(url, params=params, timeout=timeout, headers={"User-Agent": user_agent})
    resp.raise_for_status()
    xml = resp.content

    try:
        root = ElementTree.fromstring(xml)
    except ElementTree.ParseError as exc:
        log.warning("PSK Reporter XML parse failed: %s", exc)
        return None

    lines = []
    for rec in root.findall(".//reception"):
        attrs = rec.attrib
        t = _parse_time_attr(attrs.get("time")) or _parse_time_attr(attrs.get("timestamp"))
        if t is None:
            continue
        tx_grid = attrs.get("senderLocator", "")
        tx_call = attrs.get("senderCallsign", "")
        rx_grid = attrs.get("receiverLocator", "")
        rx_call = attrs.get("receiverCallsign", "")
        mode = attrs.get("mode", "")
        freq_hz = _coerce_freq_hz(attrs.get("frequency") or attrs.get("freq"))
        snr = attrs.get("sNR") or attrs.get("snr") or ""
        if freq_hz is None:
            continue
        lines.append(f"{t},{tx_grid},{tx_call},{rx_grid},{rx_call},{mode},{freq_hz},{snr}")

    if not lines:
        return None

    content = "\n".join(lines) + "\n"
    _write_cache(cache_path, content)
    return content


def fetch_wspr(
    *,
    data_root: Path,
    user_agent: str,
    timeout: float,
    max_age: int,
    query_type: str,
    query_value: str,
) -> Optional[str]:
    params: Dict[str, str] = {
        "mode": "csv",
        "last": str(max_age // 60),
    }
    if query_type == "bygrid":
        params["rxgrid"] = query_value
    elif query_type == "ofgrid":
        params["txgrid"] = query_value
    elif query_type == "bycall":
        params["rxcall"] = query_value
    elif query_type == "ofcall":
        params["txcall"] = query_value
    else:
        return None

    cache_key = f"wspr:{query_type}:{query_value}:{max_age}"
    cache_path = _cache_paths(data_root, "wspr", cache_key)
    cached = _read_cache(cache_path, max_age_seconds=max_age)
    if cached:
        return cached

    url = "https://wsprnet.org/olddb"
    resp = requests.get(url, params=params, timeout=timeout, headers={"User-Agent": user_agent})
    resp.raise_for_status()
    text = resp.text

    # Expect CSV header in WSPR mode=csv; fallback: try to parse rows separated by commas.
    lines = []
    for line in text.splitlines():
        line = line.strip()
        if not line or line.lower().startswith("date"):
            continue
        parts = [p.strip() for p in line.split(",")]
        if len(parts) < 9:
            continue
        # Typical CSV: date,time,tx_call,tx_grid,rx_call,rx_grid,snr,freq,drift,...
        date_s, time_s = parts[0], parts[1]
        try:
            dt = datetime.strptime(f"{date_s} {time_s}", "%Y-%m-%d %H:%M").replace(tzinfo=timezone.utc)
        except Exception:
            continue
        tx_call = parts[2]
        tx_grid = parts[3]
        rx_call = parts[4]
        rx_grid = parts[5]
        snr = parts[6]
        freq_hz = _coerce_freq_hz(parts[7])
        if freq_hz is None:
            continue
        lines.append(f"{int(dt.timestamp())},{tx_grid},{tx_call},{rx_grid},{rx_call},WSPR,{freq_hz},{snr}")

    if not lines:
        return None

    content = "\n".join(lines) + "\n"
    _write_cache(cache_path, content)
    return content


def fetch_rbn(
    *,
    data_root: Path,
    user_agent: str,
    timeout: float,
    max_age: int,
    query_type: str,
    query_value: str,
) -> Optional[str]:
    params: Dict[str, str] = {"format": "csv"}
    if query_type == "bygrid":
        params["rxgrid"] = query_value
    elif query_type == "ofgrid":
        params["txgrid"] = query_value
    elif query_type == "bycall":
        params["rxcall"] = query_value
    elif query_type == "ofcall":
        params["txcall"] = query_value
    else:
        return None

    cache_key = f"rbn:{query_type}:{query_value}:{max_age}"
    cache_path = _cache_paths(data_root, "rbn", cache_key)
    cached = _read_cache(cache_path, max_age_seconds=max_age)
    if cached:
        return cached

    url = "https://www.reversebeacon.net/spots.php"
    resp = requests.get(url, params=params, timeout=timeout, headers={"User-Agent": user_agent})
    resp.raise_for_status()
    text = resp.text

    lines = []
    for line in text.splitlines():
        line = line.strip()
        if not line or line.lower().startswith("date"):
            continue
        parts = [p.strip() for p in line.split(",")]
        if len(parts) < 8:
            continue
        # Common CSV: date,time,tx_call,rx_call,freq,mode,snr,dxcc,grid
        date_s, time_s = parts[0], parts[1]
        try:
            dt = datetime.strptime(f"{date_s} {time_s}", "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
        except Exception:
            continue
        tx_call = parts[2]
        rx_call = parts[3]
        freq_hz = _coerce_freq_hz(parts[4])
        mode = parts[5]
        snr = parts[6]
        tx_grid = parts[8] if len(parts) > 8 else ""
        rx_grid = ""
        if freq_hz is None:
            continue
        lines.append(f"{int(dt.timestamp())},{tx_grid},{tx_call},{rx_grid},{rx_call},{mode},{freq_hz},{snr}")

    if not lines:
        return None

    content = "\n".join(lines) + "\n"
    _write_cache(cache_path, content)
    return content
