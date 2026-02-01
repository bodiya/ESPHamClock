from __future__ import annotations

import re
from pathlib import Path

from backend.server.fetchers.phase1 import _parse_cty_dat, format_cty_output


def _first_data_line(lines: list[str]) -> str:
    for line in lines:
        if line and not line.startswith("#"):
            return line
    raise AssertionError("No data lines found")


def _float_positions(line: str) -> list[int]:
    return [m.start() for m in re.finditer(r"[-\d]+\.\d+", line)]


def test_cty_output_columns_match_gold() -> None:
    repo_root = Path(__file__).resolve().parents[3]
    src_path = repo_root / "backend" / "server" / "tests" / "fixtures" / "cty_wt_mod.dat"
    gold_path = repo_root / "backend" / "gold" / "cty" / "cty_wt_mod-ll-dxcc.txt"

    assert src_path.exists(), f"Missing {src_path}"
    assert gold_path.exists(), f"Missing {gold_path}"

    raw = src_path.read_text(encoding="utf-8", errors="replace")
    rows = _parse_cty_dat(raw)
    assert rows, "CTY parser yielded no rows"

    output = format_cty_output(rows, "TEST")
    gold_lines = gold_path.read_text(encoding="utf-8", errors="replace").splitlines()

    out_line = _first_data_line(output)
    gold_line = _first_data_line(gold_lines)

    out_positions = _float_positions(out_line)
    gold_positions = _float_positions(gold_line)

    assert len(out_positions) >= 2 and len(gold_positions) >= 2
    assert out_positions[:2] == gold_positions[:2]
