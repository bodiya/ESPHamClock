from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Optional, Tuple

import requests
from flask import Response, request

from .storage import SafePathError, resolve_under


log = logging.getLogger("hamclock-backend.fallback")


@dataclass
class CachedResponse:
    status: int
    headers: Dict[str, str]
    body: bytes
    fetched_at: Optional[datetime] = None


def _normalize_full_path(full_path: str) -> str:
    if full_path.endswith("?"):
        return full_path[:-1]
    return full_path


def _cache_paths(root: Path, path: str, query: str) -> Tuple[Path, Path]:
    safe_path = path.lstrip("/") or "root"
    if query:
        key = hashlib.sha1(query.encode("utf-8")).hexdigest()
        body_rel = Path(safe_path) / f"__query__{key}.body"
    else:
        body_rel = Path(safe_path)

    body_path = resolve_under(root, str(body_rel))
    headers_path = body_path.with_suffix(body_path.suffix + ".headers.json")
    return body_path, headers_path


def _log_request(prefix: str) -> None:
    headers = "\n".join(f"{k}: {v}" for k, v in request.headers.items())
    log.warning("%s REQUEST %s %s\n%s", prefix, request.method, request.full_path, headers)


def _is_probably_binary(body: bytes) -> bool:
    if not body:
        return False
    if b"\x00" in body:
        return True
    sample = body[:2048]
    printable = bytearray(b"\n\r\t\b")
    printable.extend(range(32, 127))
    nonprintable = sum(1 for b in sample if b not in printable)
    return (nonprintable / len(sample)) > 0.3


def _log_response(prefix: str, status: int, headers: Dict[str, str], body: bytes) -> None:
    header_lines = "\n".join(f"{k}: {v}" for k, v in headers.items())
    content_type = headers.get("Content-Type", "").lower()
    is_binary = any(
        token in content_type
        for token in (
            "image/",
            "application/octet-stream",
            "application/zip",
            "application/x-binary",
        )
    )
    if not is_binary:
        is_binary = _is_probably_binary(body)

    if is_binary:
        digest = hashlib.sha256(body).hexdigest()
        body_text = f"<binary {len(body)} bytes sha256={digest}>"
    else:
        try:
            body_text = body.decode("ISO-8859-1", errors="replace")
        except Exception:
            body_text = repr(body)
    log.warning("%s RESPONSE %d\n%s\n\n%s", prefix, status, header_lines, body_text)


def _read_cache(body_path: Path, headers_path: Path) -> Optional[CachedResponse]:
    if not body_path.exists() or not headers_path.exists():
        return None
    try:
        body = body_path.read_bytes()
        meta = json.loads(headers_path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001 - treat as cache miss
        log.warning("Fallback cache read failed: %s", exc)
        return None

    status = int(meta.get("status", 200))
    headers = {str(k): str(v) for k, v in meta.get("headers", {}).items()}
    fetched_at_raw = meta.get("fetched_at")
    fetched_at = None
    if isinstance(fetched_at_raw, str):
        try:
            fetched_at = datetime.fromisoformat(fetched_at_raw)
        except ValueError:
            fetched_at = None
    return CachedResponse(status=status, headers=headers, body=body, fetched_at=fetched_at)


def _write_cache(body_path: Path, headers_path: Path, status: int, headers: Dict[str, str], body: bytes) -> None:
    body_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_body = body_path.with_suffix(body_path.suffix + ".tmp")
    tmp_meta = headers_path.with_suffix(headers_path.suffix + ".tmp")

    tmp_body.write_bytes(body)
    meta = {
        "status": status,
        "headers": headers,
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "path": request.path,
        "query": request.query_string.decode("utf-8", errors="replace"),
    }
    tmp_meta.write_text(json.dumps(meta, indent=2, sort_keys=True), encoding="utf-8")

    tmp_body.replace(body_path)
    tmp_meta.replace(headers_path)


def fetch_with_cache(
    *,
    fallback_dir: Path,
    base_url: str,
    timeout: float,
    max_age_seconds: float,
) -> Optional[Response]:
    if request.method != "GET":
        return None

    full_path = _normalize_full_path(request.full_path)
    query = request.query_string.decode("utf-8", errors="replace")

    try:
        body_path, headers_path = _cache_paths(fallback_dir, request.path, query)
    except SafePathError:
        return None

    cached = _read_cache(body_path, headers_path)
    if cached is not None:
        if max_age_seconds > 0 and cached.fetched_at is not None:
            age = (datetime.now(timezone.utc) - cached.fetched_at).total_seconds()
            if age > max_age_seconds:
                cached = None
        if cached is not None:
            _log_request("FALLBACK CACHE")
            _log_response("FALLBACK CACHE", cached.status, cached.headers, cached.body)
            resp = Response(cached.body, status=cached.status)
            for key, value in cached.headers.items():
                if key.lower() == "content-length":
                    continue
                resp.headers[key] = value
            return resp

    _log_request("FALLBACK FETCH")
    url = f"{base_url}{full_path}"
    headers = {"User-Agent": request.headers.get("User-Agent", "")}
    resp = requests.get(url, headers=headers, timeout=timeout)
    body = resp.content
    response_headers = {k: v for k, v in resp.headers.items()}
    _log_response("FALLBACK FETCH", resp.status_code, response_headers, body)

    if resp.status_code == 200:
        _write_cache(body_path, headers_path, resp.status_code, response_headers, body)

    proxy = Response(body, status=resp.status_code)
    for key, value in response_headers.items():
        if key.lower() == "content-length":
            continue
        proxy.headers[key] = value
    return proxy


def setup_fallback_logging(log_file: Optional[str]) -> None:
    if not log_file:
        return
    handler = logging.FileHandler(log_file)
    handler.setLevel(logging.WARNING)
    formatter = logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s")
    handler.setFormatter(formatter)
    log.addHandler(handler)
