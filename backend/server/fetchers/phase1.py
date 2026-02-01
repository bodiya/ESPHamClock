from __future__ import annotations

import io
import logging
import os
import re
import zipfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

from .http import fetch_first_ok


log = logging.getLogger("hamclock-backend.fetchers.phase1")


@dataclass
class FetchContext:
    data_root: Path
    timeout: float
    user_agent: str
    hamclock_version: Optional[str] = None
    hamclock_version_info: Optional[str] = None
    rss_feeds: Optional[List[str]] = None


def _atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(content, encoding="utf-8")
    tmp.replace(path)


def _atomic_write_bytes(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_bytes(content)
    tmp.replace(path)


def _format_population(pop: int) -> str:
    if pop >= 1_000_000:
        value = round(pop / 1_000_000)
        return f"{value}M"
    if pop >= 1_000:
        value = round(pop / 1_000)
        return f"{value}K"
    return str(pop)


def _parse_country_info(raw: str) -> Dict[str, str]:
    countries: Dict[str, str] = {}
    for line in raw.splitlines():
        if not line or line.startswith("#"):
            continue
        parts = line.split("\t")
        if len(parts) < 5:
            continue
        country_code = parts[0]
        country_name = parts[4]
        countries[country_code] = country_name
    return countries


def _parse_admin1(raw: str) -> Dict[str, str]:
    admin1: Dict[str, str] = {}
    for line in raw.splitlines():
        if not line or line.startswith("#"):
            continue
        parts = line.split("\t")
        if len(parts) < 2:
            continue
        code = parts[0]
        name = parts[1]
        admin1[code] = name
    return admin1


def _render_city_line(
    name: str,
    admin1: Optional[str],
    country: Optional[str],
    pop: int,
    lat: float,
    lng: float,
) -> str:
    pieces = [name]
    if admin1:
        pieces.append(admin1)
    if country:
        pieces.append(country)
    location = ", ".join(pieces)
    pop_label = _format_population(pop)
    return f"{lat:.4f}, {lng:.4f}, \"{location}. Pop {pop_label}\""


def update_cities(ctx: FetchContext) -> bool:
    cities_url = "https://download.geonames.org/export/dump/cities15000.zip"
    admin1_url = "https://download.geonames.org/export/dump/admin1CodesASCII.txt"
    country_url = "https://download.geonames.org/export/dump/countryInfo.txt"

    cities_zip = fetch_first_ok([cities_url], ctx.timeout, ctx.user_agent).content
    admin1_raw = fetch_first_ok([admin1_url], ctx.timeout, ctx.user_agent).content.decode("utf-8")
    country_raw = fetch_first_ok([country_url], ctx.timeout, ctx.user_agent).content.decode("utf-8")

    countries = _parse_country_info(country_raw)
    admin1_map = _parse_admin1(admin1_raw)

    with zipfile.ZipFile(io.BytesIO(cities_zip)) as zf:
        with zf.open("cities15000.txt") as handle:
            lines = io.TextIOWrapper(handle, encoding="utf-8")
            output: List[str] = []
            for line in lines:
                parts = line.rstrip("\n").split("\t")
                if len(parts) < 15:
                    continue
                name = parts[1]
                lat = float(parts[4])
                lng = float(parts[5])
                country_code = parts[8]
                admin1_code = parts[10]
                population = int(parts[14] or 0)

                admin1_name = admin1_map.get(f"{country_code}.{admin1_code}")
                country_name = countries.get(country_code)

                output.append(
                    _render_city_line(
                        name=name,
                        admin1=admin1_name,
                        country=country_name,
                        pop=population,
                        lat=lat,
                        lng=lng,
                    )
                )

    target = ctx.data_root / "cities2.txt"
    _atomic_write(target, "\n".join(output) + "\n")
    log.info("Updated cities2.txt with %d cities", len(output))
    return True


def _parse_cty_simple(raw: str) -> List[Tuple[str, float, float, int]]:
    rows: List[Tuple[str, float, float, int]] = []
    for line in raw.splitlines():
        if not line or line.startswith("#"):
            continue
        parts = line.replace(",", " ").split()
        if len(parts) < 4:
            continue
        prefix = parts[0]
        try:
            lat = float(parts[1])
            lng = float(parts[2])
            dxcc = int(parts[3])
        except ValueError:
            continue
        rows.append((prefix, lat, lng, dxcc))
    return rows


def _strip_prefix_token(token: str) -> str:
    token = token.strip().rstrip(";")
    if "=" in token:
        token = token.split("=", 1)[1]
    token = re.sub(r"\\(.*?\\)", "", token)  # remove (lat lon) overrides
    token = re.sub(r"\\[.*?\\]", "", token)  # remove [dxcc] overrides
    token = re.sub(r"\\{.*?\\}", "", token)  # remove {itu} overrides
    token = re.sub(r"<.*?>", "", token)  # remove <lat/lon> overrides
    token = token.replace("*", "").replace("?", "").strip()
    return token


def _parse_cty_dat(raw: str) -> List[Tuple[str, float, float, int]]:
    rows: List[Tuple[str, float, float, int]] = []
    buffer = ""
    current_dxcc: Optional[int] = None
    for line in raw.splitlines():
        if not line:
            continue
        stripped = line.strip()
        if stripped.startswith("#"):
            if stripped.upper().startswith("# ADIF"):
                parts = stripped.split()
                if len(parts) >= 3 and parts[2].isdigit():
                    current_dxcc = int(parts[2])
            continue
        if stripped.upper().startswith("ADIF"):
            parts = stripped.split()
            if len(parts) >= 2 and parts[1].isdigit():
                current_dxcc = int(parts[1])
            continue
        buffer = f"{buffer} {line.strip()}" if buffer else line.strip()
        while ";" in buffer:
            block, buffer = buffer.split(";", 1)
            fields = [f.strip() for f in block.split(":")]
            if len(fields) < 9:
                continue
            try:
                lat = float(fields[4])
                lng = float(fields[5])
            except Exception:
                continue
            dxcc = None
            if current_dxcc is not None:
                dxcc = current_dxcc
            else:
                try:
                    dxcc = int(fields[7])
                except Exception:
                    dxcc = None
            if dxcc is None:
                continue
            primary_prefix = fields[7].strip()
            prefix_blob = ":".join(fields[8:])
            tokens = [primary_prefix] + [t.strip() for t in prefix_blob.split(",") if t.strip()]
            for token in tokens:
                if not token:
                    continue
                lat_override = re.search(r"<\\s*([-\\d.]+)\\s*[/\\\\s]\\s*([-\\d.]+)\\s*>", token)
                if not lat_override:
                    lat_override = re.search(r"\\(([-\\d.]+)\\s+([-\\d.]+)\\)", token)
                dxcc_override = re.search(r"\\[(\\d+)\\]", token)
                use_lat = lat
                use_lng = lng
                use_dxcc = dxcc
                if lat_override:
                    use_lat = float(lat_override.group(1))
                    use_lng = float(lat_override.group(2))
                if dxcc_override:
                    use_dxcc = int(dxcc_override.group(1))
                prefix = _strip_prefix_token(token)
                if prefix:
                    rows.append((prefix, use_lat, use_lng, use_dxcc))
    return rows


def format_cty_output(rows: List[Tuple[str, float, float, int]], extracted_from: str) -> List[str]:
    output = [f"# extracted from cty_wt_mod.dat on {extracted_from}"]
    output.append("# prefix     lat+N   lng+E  DXCC")
    for prefix, lat, lng, dxcc in rows:
        output.append(f"{prefix:<11}{lat:7.2f}  {lng:7.2f}  {dxcc}")
    return output


def update_cty(ctx: FetchContext) -> bool:
    urls = [
        "https://www.country-files.com/cty/cty_wt_mod.dat",
        "https://www.country-files.com/big-cty/cty_wt_mod.dat",
    ]
    result = fetch_first_ok(urls, ctx.timeout, ctx.user_agent)
    raw = result.content.decode("utf-8", errors="replace")

    rows = _parse_cty_simple(raw)
    if not rows:
        rows = _parse_cty_dat(raw)
    if not rows:
        log.warning("cty_wt_mod.dat parse yielded no rows, falling back to cty.dat")
        cty_urls = [
            "https://www.country-files.com/cty/cty.dat",
            "https://www.country-files.com/big-cty/cty.dat",
        ]
        result = fetch_first_ok(cty_urls, ctx.timeout, ctx.user_agent)
        raw = result.content.decode("utf-8", errors="replace")
        rows = _parse_cty_dat(raw)
        if not rows:
            log.warning("cty.dat parse yielded no rows")
            return False

    now = datetime.now(timezone.utc).strftime("%a %b %d %H:%M:%S %YZ")
    output = format_cty_output(rows, now)

    target = ctx.data_root / "cty" / "cty_wt_mod-ll-dxcc.txt"
    _atomic_write(target, "\n".join(output) + "\n")
    log.info("Updated cty_wt_mod-ll-dxcc.txt with %d prefixes", len(rows))
    return True


def _parse_tle(text: str) -> List[Tuple[str, str, str]]:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    triples: List[Tuple[str, str, str]] = []
    for idx in range(0, len(lines) - 2, 3):
        name = lines[idx].replace(" ", "_")
        line1 = lines[idx + 1]
        line2 = lines[idx + 2]
        if not line1.startswith("1 ") or not line2.startswith("2 "):
            continue
        triples.append((name, line1, line2))
    return triples


def update_esats(ctx: FetchContext) -> bool:
    urls = [
        "https://celestrak.org/NORAD/elements/gp.php?GROUP=amateur&FORMAT=tle",
        "https://celestrak.org/NORAD/elements/gp.php?GROUP=weather&FORMAT=tle",
        "https://celestrak.org/NORAD/elements/gp.php?CATNR=25544&FORMAT=tle",
    ]

    all_triples: Dict[str, Tuple[str, str]] = {}
    for url in urls:
        result = fetch_first_ok([url], ctx.timeout, ctx.user_agent)
        text = result.content.decode("utf-8", errors="replace")
        for name, line1, line2 in _parse_tle(text):
            all_triples[name] = (line1, line2)

    if not all_triples:
        log.warning("No TLEs parsed from CelesTrak")
        return False

    output: List[str] = []
    for name in sorted(all_triples):
        line1, line2 = all_triples[name]
        output.extend([name, line1, line2])

    target = ctx.data_root / "esats" / "esats.txt"
    _atomic_write(target, "\n".join(output) + "\n")
    log.info("Updated esats.txt with %d satellites", len(all_triples))
    return True


def update_version(ctx: FetchContext) -> bool:
    version = ctx.hamclock_version or os.environ.get("HAMCLOCK_VERSION")
    if not version:
        log.info("HAMCLOCK_VERSION not set; skipping version update")
        return False
    info = ctx.hamclock_version_info or os.environ.get("HAMCLOCK_VERSION_INFO")
    lines = [version]
    if info:
        lines.append(info)
    target = ctx.data_root / "version.txt"
    _atomic_write(target, "\n".join(lines) + "\n")
    log.info("Updated version.txt to %s", version)
    return True


PHASE1_JOBS = [
    {
        "id": "update_cities",
        "func": update_cities,
        "trigger": "interval",
        "days": 30,
        "replace_existing": True,
    },
    {
        "id": "update_cty",
        "func": update_cty,
        "trigger": "interval",
        "days": 30,
        "replace_existing": True,
    },
    {
        "id": "update_esats",
        "func": update_esats,
        "trigger": "interval",
        "hours": 3,
        "replace_existing": True,
    },
    {
        "id": "update_version",
        "func": update_version,
        "trigger": "interval",
        "hours": 12,
        "replace_existing": True,
    },
]


def run_phase1(ctx: FetchContext) -> None:
    for job in PHASE1_JOBS:
        job_name = job.get("id", "phase1")
        func = job["func"]
        try:
            ok = func(ctx)
            log.info("Phase1 job %s completed: %s", job_name, ok)
        except Exception as exc:  # noqa: BLE001 - keep server running
            log.warning("Phase1 job %s failed: %s", job_name, exc)
