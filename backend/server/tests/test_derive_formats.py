from __future__ import annotations

import json
import math
import re
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

from backend.server.fetchers.phase1 import (
    FetchContext,
    derive_cities,
    derive_cty,
    derive_esats,
    derive_version,
)
from backend.server.fetchers.phase2 import (
    derive_ssn,
    derive_ssn_history,
    derive_solar_flux,
    derive_solar_flux_history,
    derive_kindex,
    derive_solar_wind,
    derive_bz,
    derive_noaa_scales,
    derive_xray,
    derive_aurora,
    derive_dst,
    derive_drap,
)
from backend.server.fetchers.phase3 import derive_onta, derive_rss, derive_contests
from backend.server.fetchers.phase4 import derive_worldwx


FIXTURE_ROOT = Path(__file__).resolve().parent / "fixtures" / "upstream"
REPO_ROOT = Path(__file__).resolve().parents[3]
GOLD_ROOT = REPO_ROOT / "backend" / "gold"


def _ctx(tmp_dir: Path) -> FetchContext:
    return FetchContext(data_root=tmp_dir, timeout=5.0, user_agent="test-agent")


def _first_data_line(lines: list[str]) -> str:
    for line in lines:
        if line and not line.startswith("#"):
            return line
    raise AssertionError("No data lines found")


def _split_fields(line: str) -> list[str]:
    return [field for field in line.split() if field]


def _float_positions(line: str) -> list[int]:
    return [m.start() for m in re.finditer(r"[-\\d]+\\.\\d+", line)]


def _median(values: list[float]) -> float:
    if not values:
        return 0.0
    values = sorted(values)
    mid = len(values) // 2
    if len(values) % 2:
        return values[mid]
    return 0.5 * (values[mid - 1] + values[mid])


def _order_of_mag(value: float) -> int:
    if value == 0:
        return 0
    return int(math.floor(math.log10(abs(value))))


def _extract_numbers(lines: list[str]) -> list[float]:
    numbers: list[float] = []
    for line in lines:
        if not line or line.startswith("#"):
            continue
        for token in line.replace(",", " ").split():
            try:
                numbers.append(float(token))
            except Exception:
                continue
    return numbers


def _time_info(line: str) -> tuple[callable | None, int]:
    if re.match(r"^\\d{10}\\b", line):
        return lambda token: int(token), 1
    if re.match(r"^\\d{4}-\\d{2}-\\d{2}T\\d{2}:\\d{2}:\\d{2}", line):
        def _parse_iso(token: str) -> int:
            dt = datetime.strptime(token, "%Y-%m-%dT%H:%M:%S").replace(tzinfo=timezone.utc)
            return int(dt.timestamp())
        return _parse_iso, 6
    if re.match(r"^\\d{4}\\s+\\d{1,2}\\s+\\d{1,2}\\s+\\d{3,4}", line):
        def _parse_ymd(parts: list[str]) -> int:
            year, month, day, hhmm = parts[0], parts[1], parts[2], parts[3]
            hour = int(hhmm) // 100
            minute = int(hhmm) % 100
            dt = datetime(int(year), int(month), int(day), hour, minute, tzinfo=timezone.utc)
            return int(dt.timestamp())
        return _parse_ymd, 4
    return None, 0


def _parse_times(lines: list[str]) -> list[int]:
    for line in lines:
        if line and not line.startswith("#"):
            parser, drop = _time_info(line)
            if parser is None:
                return []
            times: list[int] = []
            for line in lines:
                if not line or line.startswith("#"):
                    continue
                parts = line.split()
                if drop == 4:
                    if len(parts) >= 4:
                        try:
                            times.append(parser(parts))
                        except Exception:
                            continue
                else:
                    try:
                        times.append(parser(parts[0]))
                    except Exception:
                        continue
            return times
    return []


def _numeric_values_excluding_time(lines: list[str]) -> list[float]:
    values: list[float] = []
    for line in lines:
        if not line or line.startswith("#"):
            continue
        _, drop = _time_info(line)
        numbers = [float(val) for val in re.findall(r"[-+]?\\d+(?:\\.\\d+)?(?:[eE][-+]?\\d+)?", line)]
        if drop:
            numbers = numbers[drop:]
        values.extend(numbers)
    return values


def _compare_to_gold(label: str, derived_lines: list[str], gold_lines: list[str]) -> None:
    derived_line = _first_data_line(derived_lines)
    gold_line = _first_data_line(gold_lines)
    derived_numbers_line = _numeric_values_excluding_time([derived_line])
    gold_numbers_line = _numeric_values_excluding_time([gold_line])
    derived_tokens = _split_fields(derived_line)
    gold_tokens = _split_fields(gold_line)
    derived_non_numeric = max(0, len(derived_tokens) - len(derived_numbers_line))
    gold_non_numeric = max(0, len(gold_tokens) - len(gold_numbers_line))
    if (
        len(derived_numbers_line) >= 2
        and len(gold_numbers_line) >= 2
        and derived_non_numeric <= 2
        and gold_non_numeric <= 2
    ):
        assert len(_split_fields(derived_line)) == len(_split_fields(gold_line)), f"{label}: field count mismatch"

    derived_nums = _numeric_values_excluding_time(derived_lines)
    gold_nums = _numeric_values_excluding_time(gold_lines)
    if derived_nums:
        nonzero = [v for v in derived_nums if v != 0]
        if nonzero:
            derived_nums = nonzero
    if gold_nums:
        nonzero = [v for v in gold_nums if v != 0]
        if nonzero:
            gold_nums = nonzero
    if derived_nums and gold_nums:
        derived_mag = _order_of_mag(_median(derived_nums))
        gold_mag = _order_of_mag(_median(gold_nums))
        assert abs(derived_mag - gold_mag) <= 2, f"{label}: magnitude off (derived {derived_mag}, gold {gold_mag})"

    derived_times = _parse_times(derived_lines)
    gold_times = _parse_times(gold_lines)
    if derived_times and gold_times and len(derived_times) >= 3 and len(gold_times) >= 3:
        def _median_delta(times: list[int]) -> float:
            deltas = [b - a for a, b in zip(times, times[1:])]
            return _median([float(v) for v in deltas])

        derived_delta = _median_delta(derived_times)
        gold_delta = _median_delta(gold_times)
        tolerance = max(60.0, gold_delta * 0.2)
        assert abs(derived_delta - gold_delta) <= tolerance, f"{label}: cadence off ({derived_delta}s vs {gold_delta}s)"


def test_derive_ssn_and_solar_flux_formats() -> None:
    with TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
        raw_dir = tmp_path / "raw" / "solar"
        raw_dir.mkdir(parents=True, exist_ok=True)
        (raw_dir / "daily-solar-indices.txt").write_text(
            (FIXTURE_ROOT / "daily-solar-indices.txt").read_text(encoding="utf-8"),
            encoding="utf-8",
        )
        (raw_dir / "27-day-outlook.txt").write_text(
            (FIXTURE_ROOT / "27-day-outlook.txt").read_text(encoding="utf-8"),
            encoding="utf-8",
        )

        ctx = _ctx(tmp_path)
        assert derive_ssn(ctx) is True
        assert derive_ssn_history(ctx) is True
        assert derive_solar_flux(ctx) is True
        assert derive_solar_flux_history(ctx) is True

        ssn_lines = (tmp_path / "ssn" / "ssn-31.txt").read_text(encoding="utf-8").splitlines()
        gold_ssn = (GOLD_ROOT / "ssn" / "ssn-31.txt").read_text(encoding="utf-8").splitlines()
        _compare_to_gold("ssn-31", ssn_lines, gold_ssn)

        flux_lines = (tmp_path / "solar-flux" / "solarflux-99.txt").read_text(encoding="utf-8").splitlines()
        gold_flux = (GOLD_ROOT / "solar-flux" / "solarflux-99.txt").read_text(encoding="utf-8").splitlines()
        assert len(flux_lines) == len(gold_flux)
        _compare_to_gold("solarflux-99", flux_lines, gold_flux)

        ssn_hist_lines = (tmp_path / "ssn" / "ssn-history.txt").read_text(encoding="utf-8").splitlines()
        gold_ssn_hist = (GOLD_ROOT / "ssn" / "ssn-history.txt").read_text(encoding="utf-8").splitlines()
        _compare_to_gold("ssn-history", ssn_hist_lines, gold_ssn_hist)

        flux_hist_lines = (tmp_path / "solar-flux" / "solarflux-history.txt").read_text(encoding="utf-8").splitlines()
        gold_flux_hist = (GOLD_ROOT / "solar-flux" / "solarflux-history.txt").read_text(encoding="utf-8").splitlines()
        _compare_to_gold("solarflux-history", flux_hist_lines, gold_flux_hist)


def test_derive_kindex_format_against_gold() -> None:
    with TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
        raw_dir = tmp_path / "raw" / "geomag"
        raw_dir.mkdir(parents=True, exist_ok=True)
        (raw_dir / "noaa-planetary-k-index.json").write_text(
            (FIXTURE_ROOT / "noaa-planetary-k-index.json").read_text(encoding="utf-8"),
            encoding="utf-8",
        )
        ctx = _ctx(tmp_path)
        assert derive_kindex(ctx) is True
        lines = (tmp_path / "geomag" / "kindex.txt").read_text(encoding="utf-8").splitlines()
        gold = (GOLD_ROOT / "geomag" / "kindex.txt").read_text(encoding="utf-8").splitlines()
        _compare_to_gold("kindex", lines, gold)


def test_derive_solar_wind_and_bz_formats() -> None:
    with TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
        raw_dir = tmp_path / "raw" / "solar-wind"
        raw_dir.mkdir(parents=True, exist_ok=True)
        (raw_dir / "plasma-7-day.json").write_text(
            (FIXTURE_ROOT / "dscovr_plasma_5m.json").read_text(encoding="utf-8"),
            encoding="utf-8",
        )
        (raw_dir / "mag-7-day.json").write_text(
            (FIXTURE_ROOT / "dscovr_mag_5m.json").read_text(encoding="utf-8"),
            encoding="utf-8",
        )
        ctx = _ctx(tmp_path)
        assert derive_solar_wind(ctx) is True
        assert derive_bz(ctx) is True

        sw_lines = (tmp_path / "solar-wind" / "swind-24hr.txt").read_text(encoding="utf-8").splitlines()
        gold_sw = (GOLD_ROOT / "solar-wind" / "swind-24hr.txt").read_text(encoding="utf-8").splitlines()
        _compare_to_gold("solar-wind", sw_lines, gold_sw)

        bz_lines = (tmp_path / "Bz" / "Bz.txt").read_text(encoding="utf-8").splitlines()
        gold_bz = (GOLD_ROOT / "Bz" / "Bz.txt").read_text(encoding="utf-8").splitlines()
        _compare_to_gold("Bz", bz_lines, gold_bz)


def test_derive_noaa_scales_format() -> None:
    with TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
        raw_dir = tmp_path / "raw" / "NOAASpaceWX"
        raw_dir.mkdir(parents=True, exist_ok=True)
        (raw_dir / "noaa-scales.json").write_text(
            (FIXTURE_ROOT / "noaa-scales.json").read_text(encoding="utf-8"),
            encoding="utf-8",
        )
        ctx = _ctx(tmp_path)
        assert derive_noaa_scales(ctx) is True
        lines = (tmp_path / "NOAASpaceWX" / "noaaswx.txt").read_text(encoding="utf-8").splitlines()
        assert lines and lines[0].startswith("R  ")
        assert lines[1].startswith("S  ")
        assert lines[2].startswith("G  ")
        gold = (GOLD_ROOT / "NOAASpaceWX" / "noaaswx.txt").read_text(encoding="utf-8").splitlines()
        _compare_to_gold("noaa-scales", lines, gold)


def test_derive_xray_and_aurora_formats() -> None:
    with TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
        raw_dir = tmp_path / "raw" / "xray"
        raw_dir.mkdir(parents=True, exist_ok=True)
        (raw_dir / "xrays-7-day.json").write_text(
            (FIXTURE_ROOT / "xrays-7-day.json").read_text(encoding="utf-8"),
            encoding="utf-8",
        )
        ctx = _ctx(tmp_path)
        assert derive_xray(ctx) is True
        out_lines = (tmp_path / "xray" / "xray.txt").read_text(encoding="utf-8").splitlines()
        gold_lines = (GOLD_ROOT / "xray" / "xray.txt").read_text(encoding="utf-8").splitlines()
        out_line = _first_data_line(out_lines)
        gold_line = _first_data_line(gold_lines)
        assert _float_positions(out_line)[:2] == _float_positions(gold_line)[:2]
        _compare_to_gold("xray", out_lines, gold_lines)

        raw_dir = tmp_path / "raw" / "aurora"
        raw_dir.mkdir(parents=True, exist_ok=True)
        (raw_dir / "ovation.json").write_text(
            (FIXTURE_ROOT / "ovation_aurora_latest.json").read_text(encoding="utf-8"),
            encoding="utf-8",
        )
        (raw_dir / "source.txt").write_text("ovation", encoding="utf-8")
        assert derive_aurora(ctx) is True
        aurora_lines = (tmp_path / "aurora" / "aurora.txt").read_text(encoding="utf-8").splitlines()
        gold_aurora = (GOLD_ROOT / "aurora" / "aurora.txt").read_text(encoding="utf-8").splitlines()
        assert len(aurora_lines) == len(gold_aurora)
        _compare_to_gold("aurora", aurora_lines, gold_aurora)


def test_derive_dst_and_drap_formats() -> None:
    with TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
        raw_dst = tmp_path / "raw" / "dst"
        raw_dst.mkdir(parents=True, exist_ok=True)
        (raw_dst / "kyoto-dst.json").write_text(
            (FIXTURE_ROOT / "kyoto-dst.json").read_text(encoding="utf-8"),
            encoding="utf-8",
        )
        raw_drap = tmp_path / "raw" / "drap"
        raw_drap.mkdir(parents=True, exist_ok=True)
        (raw_drap / "global.json").write_text(
            (FIXTURE_ROOT / "drap_global.json").read_text(encoding="utf-8"),
            encoding="utf-8",
        )
        ctx = _ctx(tmp_path)
        assert derive_dst(ctx) is True
        assert derive_drap(ctx) is True
        dst_lines = (tmp_path / "dst" / "dst.txt").read_text(encoding="utf-8").splitlines()
        gold_dst = (GOLD_ROOT / "dst" / "dst.txt").read_text(encoding="utf-8").splitlines()
        _compare_to_gold("dst", dst_lines, gold_dst)

        drap_lines = (tmp_path / "drap" / "stats.txt").read_text(encoding="utf-8").splitlines()
        assert drap_lines and ":" in drap_lines[0]
        gold_drap = (GOLD_ROOT / "drap" / "stats.txt").read_text(encoding="utf-8").splitlines()
        _compare_to_gold("drap", drap_lines, gold_drap)


def test_derive_onta_and_rss_formats() -> None:
    with TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
        raw_onta = tmp_path / "raw" / "onta"
        raw_onta.mkdir(parents=True, exist_ok=True)
        (raw_onta / "activator.json").write_text(
            (FIXTURE_ROOT / "pota_activator.json").read_text(encoding="utf-8"),
            encoding="utf-8",
        )
        raw_rss = tmp_path / "raw" / "rss"
        raw_rss.mkdir(parents=True, exist_ok=True)
        (raw_rss / "feed-0.xml").write_text((FIXTURE_ROOT / "arrl.rss").read_text(encoding="utf-8"), encoding="utf-8")
        (raw_rss / "feeds.json").write_text(json.dumps(["http://www.arrl.org/arrl.rss"]), encoding="utf-8")

        ctx = _ctx(tmp_path)
        assert derive_onta(ctx) is True
        assert derive_rss(ctx) is True

        onta_lines = (tmp_path / "ONTA" / "onta.txt").read_text(encoding="utf-8").splitlines()
        gold_onta = (GOLD_ROOT / "ONTA" / "onta.txt").read_text(encoding="utf-8").splitlines()
        _compare_to_gold("onta", onta_lines, gold_onta)

        rss_lines = (tmp_path / "RSS" / "web15rss.txt").read_text(encoding="utf-8").splitlines()
        assert rss_lines and ":" in rss_lines[0]
        gold_rss = (GOLD_ROOT / "RSS" / "web15rss.txt").read_text(encoding="utf-8").splitlines()
        _compare_to_gold("rss", rss_lines, gold_rss)


def test_derive_contests_format() -> None:
    with TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
        raw_contests = tmp_path / "raw" / "contests"
        raw_contests.mkdir(parents=True, exist_ok=True)
        gold = (GOLD_ROOT / "contests" / "contests311.txt").read_text(encoding="utf-8")
        (raw_contests / "contests311.txt").write_text(gold, encoding="utf-8")

        ctx = _ctx(tmp_path)
        assert derive_contests(ctx) is True

        out_lines = (tmp_path / "contests" / "contests311.txt").read_text(encoding="utf-8").splitlines()
        gold_lines = gold.splitlines()
        _compare_to_gold("contests", out_lines, gold_lines)


def test_derive_worldwx_format() -> None:
    with TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
        raw_world = tmp_path / "raw" / "worldwx"
        raw_world.mkdir(parents=True, exist_ok=True)
        (raw_world / "0.json").write_text(
            (FIXTURE_ROOT / "open-meteo-0-0.json").read_text(encoding="utf-8"),
            encoding="utf-8",
        )
        index = {"lats": [0], "lngs": [0], "generated": "2026-02-02T01:00:00Z"}
        (raw_world / "index.json").write_text(json.dumps(index), encoding="utf-8")
        ctx = _ctx(tmp_path)
        assert derive_worldwx(ctx) is True
        wx_lines = (tmp_path / "worldwx" / "wx.txt").read_text(encoding="utf-8").splitlines()
        gold_lines = (GOLD_ROOT / "worldwx" / "wx.txt").read_text(encoding="utf-8").splitlines()
        _compare_to_gold("worldwx", wx_lines, gold_lines)


def test_derive_cities_cty_esats_version_formats() -> None:
    with TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
        raw_cities = tmp_path / "raw" / "cities"
        raw_cities.mkdir(parents=True, exist_ok=True)
        city_txt = (FIXTURE_ROOT / "cities15000.txt").read_text(encoding="utf-8")
        with zipfile.ZipFile(raw_cities / "cities15000.zip", "w") as zf:
            zf.writestr("cities15000.txt", city_txt)
        (raw_cities / "admin1CodesASCII.txt").write_text(
            (FIXTURE_ROOT / "admin1CodesASCII.txt").read_text(encoding="utf-8"),
            encoding="utf-8",
        )
        (raw_cities / "countryInfo.txt").write_text(
            (FIXTURE_ROOT / "countryInfo.txt").read_text(encoding="utf-8"),
            encoding="utf-8",
        )

        raw_cty = tmp_path / "raw" / "cty"
        raw_cty.mkdir(parents=True, exist_ok=True)
        (raw_cty / "cty_wt_mod.dat").write_text(
            (REPO_ROOT / "backend" / "server" / "tests" / "fixtures" / "cty_wt_mod.dat").read_text(
                encoding="utf-8", errors="replace"
            ),
            encoding="utf-8",
        )

        raw_esats = tmp_path / "raw" / "esats"
        raw_esats.mkdir(parents=True, exist_ok=True)
        (raw_esats / "amateur.tle").write_text(
            (FIXTURE_ROOT / "esats_sample.tle").read_text(encoding="utf-8"),
            encoding="utf-8",
        )

        (tmp_path / "raw").mkdir(parents=True, exist_ok=True)
        (tmp_path / "raw" / "version.json").write_text(
            json.dumps({"version": "4.22", "info": "test"}), encoding="utf-8"
        )

        ctx = _ctx(tmp_path)
        assert derive_cities(ctx) is True
        assert derive_cty(ctx) is True
        assert derive_esats(ctx) is True
        assert derive_version(ctx) is True

        cities_lines = (tmp_path / "cities2.txt").read_text(encoding="utf-8").splitlines()
        gold_cities = (GOLD_ROOT / "cities2.txt").read_text(encoding="utf-8").splitlines()
        _compare_to_gold("cities2", cities_lines, gold_cities)

        cty_lines = (tmp_path / "cty" / "cty_wt_mod-ll-dxcc.txt").read_text(encoding="utf-8").splitlines()
        gold_cty = (GOLD_ROOT / "cty" / "cty_wt_mod-ll-dxcc.txt").read_text(encoding="utf-8").splitlines()
        assert _float_positions(_first_data_line(cty_lines))[:2] == _float_positions(_first_data_line(gold_cty))[:2]
        _compare_to_gold("cty", cty_lines, gold_cty)

        esats_lines = (tmp_path / "esats" / "esats.txt").read_text(encoding="utf-8").splitlines()
        assert esats_lines[0] == "ACS3"
        gold_esats = (GOLD_ROOT / "esats" / "esats.txt").read_text(encoding="utf-8").splitlines()
        _compare_to_gold("esats", esats_lines, gold_esats)

        version_lines = (tmp_path / "version.txt").read_text(encoding="utf-8").splitlines()
        gold_version = (GOLD_ROOT / "version.txt").read_text(encoding="utf-8").splitlines()
        _compare_to_gold("version", version_lines, gold_version)
