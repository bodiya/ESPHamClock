from __future__ import annotations

import json
from datetime import datetime, timezone, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory

from backend.server.fetchers.phase1 import FetchContext, derive_version
from backend.server.fetchers.phase2 import (
    derive_aurora,
    derive_dst,
    derive_solar_flux_history,
    derive_ssn_history,
)


FIXTURE_ROOT = Path(__file__).resolve().parent / "fixtures" / "upstream"


def _ctx(tmp_dir: Path) -> FetchContext:
    return FetchContext(data_root=tmp_dir, timeout=5.0, user_agent="test-agent")


def test_version_always_two_lines() -> None:
    with TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
        raw_dir = tmp_path / "raw"
        raw_dir.mkdir(parents=True, exist_ok=True)
        (raw_dir / "version.json").write_text(json.dumps({"version": "4.22"}), encoding="utf-8")
        ctx = _ctx(tmp_path)
        assert derive_version(ctx) is True
        lines = (tmp_path / "version.txt").read_text(encoding="utf-8").splitlines()
        assert lines == ["4.22", "No info for version  4.22"]


def test_ssn_history_bimonthly() -> None:
    with TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
        raw_dir = tmp_path / "raw" / "solar"
        raw_dir.mkdir(parents=True, exist_ok=True)
        raw = "\n".join(
            [
                "2026 1 1 100 10",
                "2026 1 2 100 20",
                "2026 2 1 100 30",
                "2026 2 2 100 40",
                "2026 3 1 100 50",
                "2026 3 2 100 60",
                "2026 4 1 100 70",
                "2026 4 2 100 80",
            ]
        )
        (raw_dir / "daily-solar-indices.txt").write_text(raw + "\n", encoding="utf-8")
        ctx = _ctx(tmp_path)
        assert derive_ssn_history(ctx) is True
        lines = (tmp_path / "ssn" / "ssn-history.txt").read_text(encoding="utf-8").splitlines()
        assert len(lines) == 2
        first_year, first_val = lines[0].split()
        second_year, second_val = lines[1].split()
        assert float(first_year) == 2026.0
        assert abs(float(first_val) - 25.0) < 0.01
        assert abs(float(second_year) - 2026.17) < 0.01
        assert abs(float(second_val) - 65.0) < 0.01


def test_solar_flux_history_monthly() -> None:
    with TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
        raw_dir = tmp_path / "raw" / "solar"
        raw_dir.mkdir(parents=True, exist_ok=True)
        raw = "\n".join(
            [
                "2026 1 1 100 10",
                "2026 1 2 110 20",
                "2026 2 1 200 30",
                "2026 2 2 220 40",
                "2026 3 1 300 50",
                "2026 3 2 330 60",
                "2026 4 1 400 70",
                "2026 4 2 440 80",
            ]
        )
        (raw_dir / "daily-solar-indices.txt").write_text(raw + "\n", encoding="utf-8")
        ctx = _ctx(tmp_path)
        assert derive_solar_flux_history(ctx) is True
        lines = (tmp_path / "solar-flux" / "solarflux-history.txt").read_text(encoding="utf-8").splitlines()
        assert len(lines) == 4
        year_val, flux_val = lines[0].split()
        assert abs(float(year_val) - 2026.00) < 0.01
        assert abs(float(flux_val) - 105.0) < 0.01
        year_val, flux_val = lines[1].split()
        assert abs(float(year_val) - 2026.08) < 0.01
        assert abs(float(flux_val) - 210.0) < 0.01


def test_history_prefers_observed_solar_cycle() -> None:
    with TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
        raw_dir = tmp_path / "raw" / "solar"
        raw_dir.mkdir(parents=True, exist_ok=True)
        observed = [
            {"time-tag": "2026-01", "ssn": 50, "f10.7": 100},
            {"time-tag": "2026-02", "ssn": 70, "f10.7": 200},
        ]
        (raw_dir / "observed-solar-cycle-indices.json").write_text(
            json.dumps(observed), encoding="utf-8"
        )
        (raw_dir / "daily-solar-indices.txt").write_text(
            "2026 1 1 10 5\n2026 2 1 20 6\n", encoding="utf-8"
        )
        ctx = _ctx(tmp_path)
        assert derive_ssn_history(ctx) is True
        assert derive_solar_flux_history(ctx) is True
        ssn_lines = (tmp_path / "ssn" / "ssn-history.txt").read_text(encoding="utf-8").splitlines()
        flux_lines = (tmp_path / "solar-flux" / "solarflux-history.txt").read_text(encoding="utf-8").splitlines()
        ssn_year, ssn_val = ssn_lines[0].split()
        assert abs(float(ssn_year) - 2026.0) < 0.01
        assert abs(float(ssn_val) - 60.0) < 0.01
        flux_year, flux_val = flux_lines[0].split()
        assert abs(float(flux_year) - 2026.0) < 0.01
        assert abs(float(flux_val) - 100.0) < 0.01


def test_aurora_hemi_power_parse() -> None:
    with TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
        raw_dir = tmp_path / "raw" / "aurora"
        raw_dir.mkdir(parents=True, exist_ok=True)
        (raw_dir / "hemi-power.txt").write_text(
            (FIXTURE_ROOT / "aurora-hemi-power.txt").read_text(encoding="utf-8"),
            encoding="utf-8",
        )
        (raw_dir / "source.txt").write_text("hemi_power", encoding="utf-8")
        ctx = _ctx(tmp_path)
        assert derive_aurora(ctx) is True
        lines = (tmp_path / "aurora" / "aurora.txt").read_text(encoding="utf-8").splitlines()
        assert len(lines) == 48
        ts, value = lines[-1].split()
        assert int(ts) > 0
        assert 0 <= float(value) < 1000


def test_dst_trims_to_24_hours() -> None:
    with TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
        raw_dir = tmp_path / "raw" / "dst"
        raw_dir.mkdir(parents=True, exist_ok=True)
        header = ["time_tag", "dst"]
        start = datetime(2026, 2, 1, 0, 0, tzinfo=timezone.utc)
        rows = [header]
        for i in range(30):
            dt = start + timedelta(hours=i)
            rows.append([dt.strftime("%Y-%m-%dT%H:%M:%S"), -10 + i])
        (raw_dir / "kyoto-dst.json").write_text(json.dumps(rows), encoding="utf-8")
        ctx = _ctx(tmp_path)
        assert derive_dst(ctx) is True
        lines = (tmp_path / "dst" / "dst.txt").read_text(encoding="utf-8").splitlines()
        assert len(lines) == 24
        assert lines[0].startswith((start + timedelta(hours=6)).strftime("%Y-%m-%dT%H:%M:%S"))
        assert lines[-1].startswith((start + timedelta(hours=29)).strftime("%Y-%m-%dT%H:%M:%S"))
