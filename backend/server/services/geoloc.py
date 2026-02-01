from __future__ import annotations

import logging
from typing import Optional, Tuple

import requests


log = logging.getLogger("hamclock-backend.geoloc")


class GeolocError(RuntimeError):
    pass


def _ip_api(ip: str, timeout: float, ua: str) -> Tuple[float, float, str]:
    url = f"http://ip-api.com/json/{ip}"
    resp = requests.get(url, timeout=timeout, headers={"User-Agent": ua})
    resp.raise_for_status()
    data = resp.json()
    if data.get("status") != "success":
        raise GeolocError(data.get("message", "ip-api failed"))
    return float(data["lat"]), float(data["lon"]), "ip-api.com"


def _ipapi(ip: str, timeout: float, ua: str) -> Tuple[float, float, str]:
    url = f"https://ipapi.co/{ip}/json/"
    resp = requests.get(url, timeout=timeout, headers={"User-Agent": ua})
    resp.raise_for_status()
    data = resp.json()
    if "latitude" not in data or "longitude" not in data:
        raise GeolocError("ipapi.co missing coordinates")
    return float(data["latitude"]), float(data["longitude"]), "ipapi.co"


def _ipwhois(ip: str, timeout: float, ua: str) -> Tuple[float, float, str]:
    url = f"https://ipwhois.io/json/{ip}"
    resp = requests.get(url, timeout=timeout, headers={"User-Agent": ua})
    resp.raise_for_status()
    data = resp.json()
    if data.get("success") is False:
        raise GeolocError(data.get("message", "ipwhois.io failed"))
    if "latitude" not in data or "longitude" not in data:
        raise GeolocError("ipwhois.io missing coordinates")
    return float(data["latitude"]), float(data["longitude"]), "ipwhois.io"


def lookup_ip(
    ip: str,
    provider: str,
    timeout: float,
    user_agent: str,
) -> Optional[Tuple[float, float, str]]:
    providers = {
        "ip-api": _ip_api,
        "ipapi": _ipapi,
        "ipwhois": _ipwhois,
    }

    if provider == "auto":
        order = ["ip-api", "ipapi", "ipwhois"]
    else:
        order = [provider]

    for name in order:
        func = providers.get(name)
        if func is None:
            continue
        try:
            return func(ip, timeout, user_agent)
        except Exception as exc:  # noqa: BLE001 - log and try next provider
            log.warning("Geoloc provider %s failed: %s", name, exc)

    return None
