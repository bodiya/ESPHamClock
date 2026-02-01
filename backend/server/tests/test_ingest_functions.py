from __future__ import annotations

import zipfile
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from backend.server.fetchers.http import FetchResult
from backend.server.fetchers.phase1 import (
    FetchContext,
    ingest_cities,
    ingest_cty,
    ingest_esats,
    ingest_version,
)
from backend.server.fetchers.phase2 import (
    ingest_daily_solar_indices,
    ingest_27_day_outlook,
    ingest_kindex,
    ingest_solar_wind,
    ingest_bz,
    ingest_noaa_scales,
    ingest_dst,
    ingest_drap,
    ingest_xray,
    ingest_aurora,
)
from backend.server.fetchers.phase3 import ingest_onta, ingest_rss


FIXTURE_ROOT = Path(__file__).resolve().parent / "fixtures" / "upstream"


def _ctx(tmp_dir: Path, **kwargs) -> FetchContext:
    return FetchContext(data_root=tmp_dir, timeout=5.0, user_agent="test-agent", **kwargs)


def _result(content: bytes) -> FetchResult:
    return FetchResult(url="test", content=content, content_type=None)


def test_ingest_phase1_sources() -> None:
    with TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
        city_txt = (FIXTURE_ROOT / "cities15000.txt").read_text(encoding="utf-8")
        zip_bytes = None
        zip_path = tmp_path / "cities15000.zip"
        with zipfile.ZipFile(zip_path, "w") as zf:
            zf.writestr("cities15000.txt", city_txt)
        zip_bytes = zip_path.read_bytes()

        admin_bytes = (FIXTURE_ROOT / "admin1CodesASCII.txt").read_bytes()
        country_bytes = (FIXTURE_ROOT / "countryInfo.txt").read_bytes()

        cty_bytes = (Path(__file__).resolve().parent / "fixtures" / "cty_wt_mod.dat").read_bytes()
        tle_bytes = (FIXTURE_ROOT / "esats_sample.tle").read_bytes()

        ctx = _ctx(tmp_path)

        with patch(
            "backend.server.fetchers.phase1.fetch_first_ok",
            side_effect=[_result(zip_bytes), _result(admin_bytes), _result(country_bytes)],
        ):
            assert ingest_cities(ctx) is True
        assert (tmp_path / "raw" / "cities" / "cities15000.zip").exists()

        with patch(
            "backend.server.fetchers.phase1.fetch_first_ok",
            side_effect=[_result(cty_bytes), _result(cty_bytes)],
        ):
            assert ingest_cty(ctx) is True
        assert (tmp_path / "raw" / "cty" / "cty_wt_mod.dat").exists()

        with patch(
            "backend.server.fetchers.phase1.fetch_first_ok",
            side_effect=[_result(tle_bytes), _result(tle_bytes), _result(tle_bytes)],
        ):
            assert ingest_esats(ctx) is True
        assert (tmp_path / "raw" / "esats" / "amateur.tle").exists()

        ctx_version = _ctx(tmp_path, hamclock_version="4.22", hamclock_version_info="test")
        assert ingest_version(ctx_version) is True
        assert (tmp_path / "raw" / "version.json").exists()


def test_ingest_phase2_sources() -> None:
    with TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
        ctx = _ctx(tmp_path)

        with patch(
            "backend.server.fetchers.phase2.fetch_first_ok",
            return_value=_result((FIXTURE_ROOT / "daily-solar-indices.txt").read_bytes()),
        ):
            assert ingest_daily_solar_indices(ctx) is True
        assert (tmp_path / "raw" / "solar" / "daily-solar-indices.txt").exists()

        with patch(
            "backend.server.fetchers.phase2.fetch_first_ok",
            return_value=_result((FIXTURE_ROOT / "27-day-outlook.txt").read_bytes()),
        ):
            assert ingest_27_day_outlook(ctx) is True
        assert (tmp_path / "raw" / "solar" / "27-day-outlook.txt").exists()

        with patch(
            "backend.server.fetchers.phase2.fetch_first_ok",
            return_value=_result((FIXTURE_ROOT / "noaa-planetary-k-index.json").read_bytes()),
        ):
            assert ingest_kindex(ctx) is True
        assert (tmp_path / "raw" / "geomag" / "noaa-planetary-k-index.json").exists()

        with patch(
            "backend.server.fetchers.phase2.fetch_first_ok",
            return_value=_result((FIXTURE_ROOT / "dscovr_plasma_5m.json").read_bytes()),
        ):
            assert ingest_solar_wind(ctx) is True
        assert (tmp_path / "raw" / "solar-wind" / "plasma-7-day.json").exists()

        with patch(
            "backend.server.fetchers.phase2.fetch_first_ok",
            return_value=_result((FIXTURE_ROOT / "dscovr_mag_5m.json").read_bytes()),
        ):
            assert ingest_bz(ctx) is True
        assert (tmp_path / "raw" / "solar-wind" / "mag-7-day.json").exists()

        with patch(
            "backend.server.fetchers.phase2.fetch_first_ok",
            return_value=_result((FIXTURE_ROOT / "noaa-scales.json").read_bytes()),
        ):
            assert ingest_noaa_scales(ctx) is True
        assert (tmp_path / "raw" / "NOAASpaceWX" / "noaa-scales.json").exists()

        with patch(
            "backend.server.fetchers.phase2.fetch_first_ok",
            return_value=_result((FIXTURE_ROOT / "kyoto-dst.json").read_bytes()),
        ):
            assert ingest_dst(ctx) is True
        assert (tmp_path / "raw" / "dst" / "kyoto-dst.json").exists()

        with patch(
            "backend.server.fetchers.phase2.fetch_first_ok",
            return_value=_result((FIXTURE_ROOT / "drap_global.json").read_bytes()),
        ):
            assert ingest_drap(ctx) is True
        assert (tmp_path / "raw" / "drap" / "global.json").exists()

        with patch(
            "backend.server.fetchers.phase2.fetch_first_ok",
            return_value=_result((FIXTURE_ROOT / "xrays-7-day.json").read_bytes()),
        ):
            assert ingest_xray(ctx) is True
        assert (tmp_path / "raw" / "xray" / "xrays-7-day.json").exists()

        hemi_bytes = (FIXTURE_ROOT / "aurora-hemi-power.txt").read_bytes()
        with patch(
            "backend.server.fetchers.phase2.fetch_first_ok",
            return_value=_result(hemi_bytes),
        ):
            assert ingest_aurora(ctx) is True
        assert (tmp_path / "raw" / "aurora" / "hemi-power.txt").exists()


def test_ingest_phase3_sources() -> None:
    with TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
        ctx = _ctx(tmp_path, rss_feeds=["http://www.arrl.org/arrl.rss"])

        with patch(
            "backend.server.fetchers.phase3.fetch_first_ok",
            return_value=_result((FIXTURE_ROOT / "pota_activator.json").read_bytes()),
        ):
            assert ingest_onta(ctx) is True
        assert (tmp_path / "raw" / "onta" / "activator.json").exists()

        with patch(
            "backend.server.fetchers.phase3.fetch_first_ok",
            return_value=_result((FIXTURE_ROOT / "arrl.rss").read_bytes()),
        ):
            assert ingest_rss(ctx) is True
        assert (tmp_path / "raw" / "rss" / "feed-0.xml").exists()
