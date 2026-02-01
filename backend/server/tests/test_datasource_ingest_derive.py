from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from backend.server.fetchers.phase1 import FetchContext
from backend.server.fetchers.http import FetchResult
from backend.server.fetchers.phase2 import ingest_xray, derive_xray, ingest_aurora, derive_aurora


def _make_ctx(tmp_path: Path) -> FetchContext:
    return FetchContext(data_root=tmp_path, timeout=5.0, user_agent="test-agent")


def test_xray_ingest_and_derive() -> None:
    base_time = datetime(2026, 1, 31, 0, 0, tzinfo=timezone.utc)
    data = []
    for i in range(5):
        ts = (base_time + timedelta(minutes=10 * i)).strftime("%Y-%m-%dT%H:%M:%S")
        data.append({"time_tag": ts, "flux": 1e-8, "energy": "0.05-0.4nm"})
        data.append({"time_tag": ts, "flux": 2e-7, "energy": "0.1-0.8nm"})
    payload = json.dumps(data).encode("utf-8")

    with TemporaryDirectory() as tmp_dir:
        ctx = _make_ctx(Path(tmp_dir))
        with patch(
            "backend.server.fetchers.phase2.fetch_first_ok",
            return_value=FetchResult(url="x", content=payload, content_type="application/json"),
        ):
            assert ingest_xray(ctx) is True

        raw_path = Path(tmp_dir) / "raw" / "xray" / "xrays-7-day.json"
        assert raw_path.exists()

        assert derive_xray(ctx) is True
        out_path = Path(tmp_dir) / "xray" / "xray.txt"
        lines = out_path.read_text(encoding="utf-8").splitlines()
        assert len(lines) == 5
        assert lines[0].startswith("2026  1 31")
        assert "1.00e-08" in lines[0]
        assert "2.00e-07" in lines[0]


def test_aurora_ingest_and_derive_ovation() -> None:
    ovation = {
        "time_tag": "2026-01-31T00:00:00Z",
        "coordinates": [
            [10, 10, 12],
            [20, 20, 33],
            [30, 30, 25],
        ],
    }

    with TemporaryDirectory() as tmp_dir:
        ctx = _make_ctx(Path(tmp_dir))
        with patch("backend.server.fetchers.phase2.fetch_first_ok", side_effect=RuntimeError("fail")):
            with patch(
                "backend.server.fetchers.phase2._load_json",
                side_effect=[None, ovation],
            ):
                assert ingest_aurora(ctx) is True

        raw_dir = Path(tmp_dir) / "raw" / "aurora"
        assert (raw_dir / "ovation.json").exists()
        assert (raw_dir / "source.txt").read_text(encoding="utf-8").strip() == "ovation"

        assert derive_aurora(ctx) is True
        out_path = Path(tmp_dir) / "aurora" / "aurora.txt"
        lines = out_path.read_text(encoding="utf-8").splitlines()
        assert len(lines) >= 1
        assert lines[-1].endswith("33")
