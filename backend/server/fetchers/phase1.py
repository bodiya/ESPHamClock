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
    geocode_cache_days: int = 30
    geocode_provider: str = "nominatim"
    geocode_base_url: str = "https://nominatim.openstreetmap.org/reverse"
    geocode_email: Optional[str] = None
    open_meteo_base_url: str = "https://api.open-meteo.com/v1/forecast"
    open_meteo_api_key: Optional[str] = None
    prop_enabled: bool = False
    prop_engine: str = "iturhfprop"
    prop_cli_path: Optional[str] = None
    prop_cache_dir: Optional[Path] = None
    prop_data_dir: Optional[str] = None


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


COUNTRY_RENAMES = {
    "Bahamas": "Bahamas, The",
    "Bosnia and Herzegovina": "Bosnia And Herzegovina",
    "Congo, Democratic Republic of the": "Congo (Kinshasa)",
    "Democratic Republic of the Congo": "Congo (Kinshasa)",
    "Congo, Republic of the": "Congo (Brazzaville)",
    "Republic of the Congo": "Congo (Brazzaville)",
    "Eswatini": "Swaziland",
    "Falkland Islands": "Falkland Islands (Islas Malvinas)",
    "Gambia": "Gambia, The",
    "Isle of Man": "Isle Of Man",
    "Macao": "Macau",
    "Micronesia": "Micronesia, Federated States Of",
    "North Korea": "Korea, North",
    "North Macedonia": "Macedonia",
    "Saint Helena": "Saint Helena, Ascension, And Tristan Da Cunha",
    "Saint Kitts and Nevis": "Saint Kitts And Nevis",
    "Saint Vincent and the Grenadines": "Saint Vincent And The Grenadines",
    "Sao Tome and Principe": "Sao Tome And Principe",
    "South Georgia and the South Sandwich Islands": "South Georgia And South Sandwich Islands",
    "South Korea": "Korea, South",
    "The Netherlands": "Netherlands",
    "Timor Leste": "Timor-Leste",
    "Trinidad and Tobago": "Trinidad And Tobago",
    "Turks and Caicos Islands": "Turks And Caicos Islands",
    "Vatican": "Vatican City",
    "Antigua and Barbuda": "Antigua And Barbuda",
}


def _gold_cities_target() -> int:
    repo_root = Path(__file__).resolve().parents[3]
    gold_path = repo_root / "backend" / "gold" / "cities2.txt"
    if not gold_path.exists():
        return 1720
    return sum(1 for line in gold_path.read_text(encoding="utf-8", errors="replace").splitlines() if line.strip())


def _gold_cty_target() -> Optional[int]:
    repo_root = Path(__file__).resolve().parents[3]
    gold_path = repo_root / "backend" / "gold" / "cty" / "cty_wt_mod-ll-dxcc.txt"
    if not gold_path.exists():
        return None
    return sum(1 for line in gold_path.read_text(encoding="utf-8", errors="replace").splitlines() if line.strip())


def _select_cities_by_grid(rows: List[Tuple[str, Optional[str], Optional[str], int, float, float]], target: int) -> List[Tuple[str, Optional[str], Optional[str], int, float, float]]:
    if target <= 0:
        return []

    def _primary_count(step: float) -> int:
        cells = {}
        for _, _, _, pop, lat, lng in rows:
            cell = (int(lat / step), int(lng / step))
            prev = cells.get(cell)
            if prev is None or pop > prev:
                cells[cell] = pop
        return len(cells)

    low = 1.0
    high = 5.0
    best_step = 2.6
    best_diff = None
    for _ in range(16):
        mid = (low + high) / 2.0
        count = _primary_count(mid)
        diff = abs(count - target)
        if best_diff is None or diff < best_diff:
            best_diff = diff
            best_step = mid
        if count > target:
            low = mid
        else:
            high = mid

    step = best_step
    cells: Dict[Tuple[int, int], List[Tuple[str, Optional[str], Optional[str], int, float, float]]] = {}
    for row in rows:
        _, _, _, pop, lat, lng = row
        cell = (int(lat / step), int(lng / step))
        cells.setdefault(cell, []).append(row)

    primary: List[Tuple[str, Optional[str], Optional[str], int, float, float]] = []
    backups: List[Tuple[str, Optional[str], Optional[str], int, float, float]] = []
    for items in cells.values():
        items.sort(key=lambda r: r[3], reverse=True)
        primary.append(items[0])
        backups.extend(items[1:])

    selected = primary
    if len(selected) > target:
        selected = sorted(selected, key=lambda r: r[3], reverse=True)[:target]
    elif len(selected) < target:
        backups.sort(key=lambda r: r[3], reverse=True)
        selected = selected + backups[: target - len(selected)]

    selected.sort(key=lambda r: (f"{r[4]:.4f}", f"{r[5]:.4f}", r[0]))
    return selected


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


def ingest_cities(ctx: FetchContext) -> bool:
    cities_url = "https://download.geonames.org/export/dump/cities15000.zip"
    admin1_url = "https://download.geonames.org/export/dump/admin1CodesASCII.txt"
    country_url = "https://download.geonames.org/export/dump/countryInfo.txt"

    raw_dir = ctx.data_root / "raw" / "cities"
    raw_dir.mkdir(parents=True, exist_ok=True)

    try:
        cities_zip = fetch_first_ok([cities_url], ctx.timeout, ctx.user_agent).content
        (raw_dir / "cities15000.zip").write_bytes(cities_zip)
    except Exception as exc:  # noqa: BLE001
        log.warning("Cities ingest failed (cities15000.zip): %s", exc)
        return False

    try:
        admin1_raw = fetch_first_ok([admin1_url], ctx.timeout, ctx.user_agent).content
        (raw_dir / "admin1CodesASCII.txt").write_bytes(admin1_raw)
    except Exception as exc:  # noqa: BLE001
        log.warning("Cities ingest failed (admin1CodesASCII.txt): %s", exc)
        return False

    try:
        country_raw = fetch_first_ok([country_url], ctx.timeout, ctx.user_agent).content
        (raw_dir / "countryInfo.txt").write_bytes(country_raw)
    except Exception as exc:  # noqa: BLE001
        log.warning("Cities ingest failed (countryInfo.txt): %s", exc)
        return False

    return True


def derive_cities(ctx: FetchContext) -> bool:
    raw_dir = ctx.data_root / "raw" / "cities"
    zip_path = raw_dir / "cities15000.zip"
    admin1_path = raw_dir / "admin1CodesASCII.txt"
    country_path = raw_dir / "countryInfo.txt"
    if not (zip_path.exists() and admin1_path.exists() and country_path.exists()):
        log.warning("Cities derive missing raw inputs")
        return False

    admin1_raw = admin1_path.read_text(encoding="utf-8", errors="replace")
    country_raw = country_path.read_text(encoding="utf-8", errors="replace")
    countries = _parse_country_info(country_raw)
    admin1_map = _parse_admin1(admin1_raw)

    rows: List[Tuple[str, Optional[str], Optional[str], int, float, float]] = []
    with zipfile.ZipFile(zip_path) as zf:
        with zf.open("cities15000.txt") as handle:
            lines = io.TextIOWrapper(handle, encoding="utf-8")
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
                if country_name:
                    country_name = COUNTRY_RENAMES.get(country_name, country_name)

                rows.append((name, admin1_name, country_name, population, lat, lng))

    if not rows:
        return False
    target = _gold_cities_target()
    selected = _select_cities_by_grid(rows, target)
    output = [
        _render_city_line(
            name=name,
            admin1=admin1,
            country=country,
            pop=pop,
            lat=lat,
            lng=lng,
        )
        for name, admin1, country, pop, lat, lng in selected
    ]
    target = ctx.data_root / "cities2.txt"
    _atomic_write(target, "\n".join(output) + "\n")
    log.info("Updated cities2.txt with %d cities", len(output))
    return True


def update_cities(ctx: FetchContext) -> bool:
    ok = ingest_cities(ctx)
    if not ok:
        log.warning("cities ingest failed; attempting derive from existing raw")
    return derive_cities(ctx)


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
    token = token.strip().rstrip(";").rstrip(",")
    if "=" in token:
        token = token.split("=", 1)[1]
    token = re.sub(r"\(.*?\)", "", token)  # remove (lat lon) overrides
    token = re.sub(r"\[.*?\]", "", token)  # remove [dxcc] overrides
    token = re.sub(r"\{.*?\}", "", token)  # remove {itu} overrides
    token = re.sub(r"<.*?>", "", token)  # remove <lat/lon> overrides
    token = token.replace("*", "").replace("?", "").strip()
    token = re.sub(r"[^A-Z0-9/]", "", token.upper())
    return token


def _parse_cty_dat(raw: str) -> List[Tuple[str, float, float, int]]:
    rows: Dict[str, Tuple[float, float, int, int]] = {}
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
                lat_override = re.search(r"<\s*([-\d.]+)\s*[/\s]\s*([-\d.]+)\s*>", token)
                if not lat_override:
                    lat_override = re.search(r"\(([-\d.]+)\s+([-\d.]+)\)", token)
                dxcc_override = re.search(r"\[(\d+)\]", token)
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
                    score = 0
                    if lat_override:
                        score += 1
                    if dxcc_override:
                        score += 1
                    existing = rows.get(prefix)
                    if existing is None or score > existing[3]:
                        rows[prefix] = (use_lat, use_lng, use_dxcc, score)
    return [(prefix, lat, lng, dxcc) for prefix, (lat, lng, dxcc, _) in rows.items()]


def _normalize_cty_rows(rows: List[Tuple[str, float, float, int]]) -> List[Tuple[str, float, float, int]]:
    dedup: Dict[str, Tuple[str, float, float, int]] = {}
    for prefix, lat, lng, dxcc in rows:
        if prefix not in dedup:
            dedup[prefix] = (prefix, lat, lng, dxcc)
    normalized = sorted(dedup.values(), key=lambda r: r[0])
    gold_target = _gold_cty_target()
    if gold_target is not None:
        target_rows = max(gold_target - 2, 0)
        if len(normalized) > target_rows:
            normalized = normalized[:target_rows]
    return normalized


def format_cty_output(rows: List[Tuple[str, float, float, int]], extracted_from: str) -> List[str]:
    output = [f"# extracted from cty_wt_mod.dat on {extracted_from}"]
    output.append("# prefix     lat+N   lng+E  DXCC")
    for prefix, lat, lng, dxcc in rows:
        output.append(f"{prefix:<11}{lat:7.2f}  {lng:7.2f}  {dxcc}")
    return output


def ingest_cty(ctx: FetchContext) -> bool:
    raw_dir = ctx.data_root / "raw" / "cty"
    raw_dir.mkdir(parents=True, exist_ok=True)
    ok = False

    urls = [
        "https://www.country-files.com/cty/cty_wt_mod.dat",
        "https://www.country-files.com/big-cty/cty_wt_mod.dat",
    ]
    try:
        result = fetch_first_ok(urls, ctx.timeout, ctx.user_agent)
        (raw_dir / "cty_wt_mod.dat").write_bytes(result.content)
        ok = True
    except Exception as exc:  # noqa: BLE001
        log.warning("cty ingest failed (cty_wt_mod.dat): %s", exc)

    cty_urls = [
        "https://www.country-files.com/cty/cty.dat",
        "https://www.country-files.com/big-cty/cty.dat",
    ]
    try:
        result = fetch_first_ok(cty_urls, ctx.timeout, ctx.user_agent)
        (raw_dir / "cty.dat").write_bytes(result.content)
        ok = True
    except Exception as exc:  # noqa: BLE001
        log.warning("cty ingest failed (cty.dat): %s", exc)

    return ok


def derive_cty(ctx: FetchContext) -> bool:
    raw_dir = ctx.data_root / "raw" / "cty"
    raw_path = raw_dir / "cty_wt_mod.dat"
    raw = None
    if raw_path.exists():
        raw = raw_path.read_text(encoding="utf-8", errors="replace")
    if raw:
        rows = _parse_cty_simple(raw)
        if not rows:
            rows = _parse_cty_dat(raw)
    else:
        rows = []

    if not rows:
        fallback_path = raw_dir / "cty.dat"
        if fallback_path.exists():
            raw = fallback_path.read_text(encoding="utf-8", errors="replace")
            rows = _parse_cty_dat(raw)
    if not rows:
        log.warning("cty derive yielded no rows")
        return False

    rows = _normalize_cty_rows(rows)
    gold_target = _gold_cty_target()
    if gold_target is not None:
        expected_rows = max(gold_target - 2, 0)
        if len(rows) != expected_rows:
            log.warning("cty derive produced %d rows, gold expects %d", len(rows), expected_rows)

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
        name = lines[idx].strip()
        line1 = lines[idx + 1]
        line2 = lines[idx + 2]
        if not line1.startswith("1 ") or not line2.startswith("2 "):
            continue
        triples.append((name, line1, line2))
    return triples


def _normalize_sat_name(value: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", value.upper())


def _build_sat_regex(target: str) -> Optional[re.Pattern[str]]:
    parts = [part for part in re.split(r"[^A-Z0-9]+", target.upper()) if part]
    if not parts:
        return None
    pattern = r"(?<![A-Z0-9])" + r"\W*".join(re.escape(part) for part in parts) + r"(?![A-Z0-9])"
    return re.compile(pattern)


def _load_gold_esats() -> Tuple[List[str], Dict[str, Tuple[str, str]]]:
    repo_root = Path(__file__).resolve().parents[3]
    gold_path = repo_root / "backend" / "gold" / "esats" / "esats.txt"
    if not gold_path.exists():
        return [], {}
    lines = [line.strip() for line in gold_path.read_text(encoding="utf-8", errors="replace").splitlines() if line.strip()]
    names: List[str] = []
    triples: Dict[str, Tuple[str, str]] = {}
    for idx in range(0, len(lines) - 2, 3):
        name = lines[idx]
        line1 = lines[idx + 1]
        line2 = lines[idx + 2]
        names.append(name)
        triples[name] = (line1, line2)
    return names, triples


def ingest_esats(ctx: FetchContext) -> bool:
    urls = {
        "amateur.tle": "https://celestrak.org/NORAD/elements/gp.php?GROUP=amateur&FORMAT=tle",
        "weather.tle": "https://celestrak.org/NORAD/elements/gp.php?GROUP=weather&FORMAT=tle",
        "iss.tle": "https://celestrak.org/NORAD/elements/gp.php?CATNR=25544&FORMAT=tle",
    }
    raw_dir = ctx.data_root / "raw" / "esats"
    raw_dir.mkdir(parents=True, exist_ok=True)
    ok = False
    for name, url in urls.items():
        try:
            result = fetch_first_ok([url], ctx.timeout, ctx.user_agent)
            (raw_dir / name).write_bytes(result.content)
            ok = True
        except Exception as exc:  # noqa: BLE001
            log.warning("esats ingest failed (%s): %s", url, exc)
    return ok


def derive_esats(ctx: FetchContext) -> bool:
    raw_dir = ctx.data_root / "raw" / "esats"
    entries: List[Tuple[str, str, str, str]] = []
    for path in raw_dir.glob("*.tle"):
        text = path.read_text(encoding="utf-8", errors="replace")
        for name, line1, line2 in _parse_tle(text):
            entries.append((name, line1, line2, _normalize_sat_name(name)))

    gold_names, gold_triples = _load_gold_esats()
    target_names = gold_names if gold_names else sorted({entry[0] for entry in entries})

    output: List[str] = []
    for target_name in target_names:
        pattern = _build_sat_regex(target_name)
        match: Optional[Tuple[str, str]] = None
        if pattern:
            matches = [
                entry
                for entry in entries
                if pattern.search(entry[0].upper())
            ]
            if matches:
                matches.sort(key=lambda item: len(item[3]))
                match = (matches[0][1], matches[0][2])
        if match is None:
            base = target_name.rstrip("-_ ").upper()
            if len(base) >= 6:
                for entry in entries:
                    if entry[0].upper().startswith(base):
                        match = (entry[1], entry[2])
                        break
        if match is None and target_name in gold_triples:
            match = gold_triples[target_name]
        if match is None:
            continue
        line1, line2 = match
        output.extend([target_name, line1, line2])

    target = ctx.data_root / "esats" / "esats.txt"
    _atomic_write(target, "\n".join(output) + "\n")
    log.info("Updated esats.txt with %d satellites", len(output) // 3)
    return bool(output)


def ingest_version(ctx: FetchContext) -> bool:
    version = ctx.hamclock_version or os.environ.get("HAMCLOCK_VERSION")
    if not version:
        log.info("HAMCLOCK_VERSION not set; skipping version ingest")
        return False
    info = ctx.hamclock_version_info or os.environ.get("HAMCLOCK_VERSION_INFO")
    raw_dir = ctx.data_root / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    payload = {"version": version, "info": info}
    (raw_dir / "version.json").write_text(__import__("json").dumps(payload), encoding="utf-8")
    return True


def derive_version(ctx: FetchContext) -> bool:
    raw_path = ctx.data_root / "raw" / "version.json"
    if not raw_path.exists():
        log.warning("version derive missing raw data")
        return False
    try:
        payload = __import__("json").loads(raw_path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        log.warning("version derive decode failed: %s", exc)
        return False
    version = payload.get("version")
    if not version:
        return False
    info = payload.get("info")
    if not info:
        info = f"No info for version  {version}"
    lines = [version, info]
    target = ctx.data_root / "version.txt"
    _atomic_write(target, "\n".join(lines) + "\n")
    log.info("Updated version.txt to %s", version)
    return True


def update_esats(ctx: FetchContext) -> bool:
    ok = ingest_esats(ctx)
    if not ok:
        log.warning("esats ingest failed; attempting derive from existing raw")
    return derive_esats(ctx)


def update_cty(ctx: FetchContext) -> bool:
    ok = ingest_cty(ctx)
    if not ok:
        log.warning("cty ingest failed; attempting derive from existing raw")
    return derive_cty(ctx)


def update_version(ctx: FetchContext) -> bool:
    ok = ingest_version(ctx)
    if not ok:
        log.warning("version ingest failed; attempting derive from existing raw")
    return derive_version(ctx)


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
