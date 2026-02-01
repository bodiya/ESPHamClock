from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Iterable, Optional

import requests


log = logging.getLogger("hamclock-backend.fetchers")


@dataclass
class FetchResult:
    url: str
    content: bytes
    content_type: Optional[str]


def fetch_bytes(url: str, timeout: float, user_agent: str) -> FetchResult:
    resp = requests.get(url, timeout=timeout, headers={"User-Agent": user_agent})
    resp.raise_for_status()
    return FetchResult(url=url, content=resp.content, content_type=resp.headers.get("Content-Type"))


def fetch_first_ok(urls: Iterable[str], timeout: float, user_agent: str) -> FetchResult:
    last_exc: Optional[Exception] = None
    for url in urls:
        try:
            return fetch_bytes(url, timeout, user_agent)
        except Exception as exc:  # noqa: BLE001 - keep trying
            log.warning("Fetch failed for %s: %s", url, exc)
            last_exc = exc
    if last_exc is not None:
        raise last_exc
    raise RuntimeError("No URLs provided")
