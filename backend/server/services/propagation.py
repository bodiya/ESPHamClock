from __future__ import annotations

import csv
import hashlib
import math
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from .prop import run_prop_command


BAND_FREQS_MHZ = [3.5, 5.3, 7.0, 10.1, 14.1, 18.1, 21.1, 24.9, 28.2]
BAND_LABELS = ["80", "60", "40", "30", "20", "17", "15", "12", "10"]


def _format_cache_key(query: str) -> str:
    return hashlib.sha1(query.encode("utf-8")).hexdigest()


def _read_cached(path: Path, max_age_seconds: float) -> Optional[str]:
    if not path.exists():
        return None
    if max_age_seconds > 0:
        age = time.time() - path.stat().st_mtime
        if age > max_age_seconds:
            return None
    return path.read_text(encoding="utf-8", errors="replace")


def _write_cached(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(content, encoding="utf-8")
    tmp.replace(path)


def _txpower_dbkw(watts: int) -> float:
    kw = max(watts, 1) / 1000.0
    return 10.0 * math.log10(kw)


def _mode_config(mode: int) -> Tuple[str, int, int, int]:
    # returns (modulation, bandwidth_hz, snrr, snrxxp)
    if mode == 38:  # SSB
        return "ANALOG", 2700, 10, 50
    if mode == 49:  # AM
        return "ANALOG", 6000, 10, 50
    if mode == 19:  # CW
        return "ANALOG", 500, 6, 50
    if mode == 22:  # RTTY
        return "DIGITAL", 250, 0, 50
    if mode == 3:  # WSPR
        return "DIGITAL", 50, 0, 50
    if mode == 13:  # FT8
        return "DIGITAL", 50, 0, 50
    if mode == 17:  # FT4
        return "DIGITAL", 90, 0, 50
    return "ANALOG", 2700, 10, 50


def _build_input_file(
    *,
    data_dir: str,
    output_path: str,
    txlat: float,
    txlng: float,
    rxlat: float,
    rxlng: float,
    year: int,
    month: int,
    ssn: int,
    power_w: int,
    mode: int,
    short_path: bool,
) -> str:
    modulation, bw, snrr, snrxxp = _mode_config(mode)
    hours = ",".join(str(h) for h in range(1, 25))
    freqs = ",".join(f"{f:.1f}" for f in BAND_FREQS_MHZ)

    lines = [
        f"DataFilePath {data_dir}",
        f"RptFilePath {output_path}",
        "RptFileFormat RPT_OCR",
        "PathName HamClock",
        "PathTXName TX",
        "PathRXName RX",
        f"Path.L_tx.lat {txlat}",
        f"Path.L_tx.lng {txlng}",
        f"Path.L_rx.lat {rxlat}",
        f"Path.L_rx.lng {rxlng}",
        f"Path.year {year}",
        f"Path.month {month}",
        f"Path.hour {hours}",
        f"Path.frequency {freqs}",
        f"Path.SSN {ssn}",
        f"Path.txpower {_txpower_dbkw(power_w):.2f}",
        f"Path.BW {bw}",
        f"Path.SNRr {snrr}",
        f"Path.SNRXXp {snrxxp}",
        "Path.ManMadeNoise RESIDENTIAL",
        f"Path.SorL {'SHORTPATH' if short_path else 'LONGPATH'}",
        f"Path.Modulation {modulation}",
        "TXAntFilePath ISOTROPIC",
        "RXAntFilePath ISOTROPIC",
        "AntennaOrientation TX2RX",
        "TXGOS 0",
        "RXGOS 0",
    ]

    if modulation == "DIGITAL":
        lines.extend(
            [
                "Path.SIRr 0",
                "Path.A 0",
                "Path.TW 0",
                "Path.FW 0",
                "Path.T0 0",
                "Path.F0 0",
            ]
        )

    return "\n".join(lines) + "\n"


def _parse_iturhfprop_csv(path: Path) -> Optional[Dict[Tuple[int, float], float]]:
    if not path.exists():
        return None
    with path.open("r", encoding="utf-8", errors="replace") as handle:
        reader = csv.reader(handle)
        rows = list(reader)

    if not rows:
        return None

    header = [h.strip().lower() for h in rows[0]]
    if any(any(c.isalpha() for c in h) for h in header):
        data_rows = rows[1:]
    else:
        header = []
        data_rows = rows

    hour_idx = None
    freq_idx = None
    ocr_idx = None
    for i, name in enumerate(header):
        if hour_idx is None and "hour" in name:
            hour_idx = i
        if freq_idx is None and ("freq" in name or "frequency" in name):
            freq_idx = i
        if ocr_idx is None and "ocr" in name:
            ocr_idx = i

    if hour_idx is None:
        hour_idx = 0
    if freq_idx is None:
        freq_idx = 1 if len(data_rows[0]) > 1 else None
    if ocr_idx is None:
        ocr_idx = -1

    results: Dict[Tuple[int, float], float] = {}
    for row in data_rows:
        if not row or len(row) <= max(hour_idx, ocr_idx, freq_idx or 0):
            continue
        try:
            hour = int(float(row[hour_idx]))
            if freq_idx is not None:
                freq = float(row[freq_idx])
            else:
                freq = 0.0
            ocr = float(row[ocr_idx])
        except Exception:
            continue
        results[(hour, freq)] = ocr / 100.0

    return results


def compute_band_conditions(
    *,
    query: str,
    cache_dir: Path,
    cli_path: str,
    data_dir: str,
    txlat: float,
    txlng: float,
    rxlat: float,
    rxlng: float,
    year: int,
    month: int,
    utc_hour: int,
    ssn: int,
    power_w: int,
    mode: int,
    short_path: bool,
) -> Optional[str]:
    cache_key = _format_cache_key(query)
    cache_path = cache_dir / f"bc-{cache_key}.txt"
    cached = _read_cached(cache_path, max_age_seconds=12 * 3600)
    if cached:
        return cached

    work_dir = cache_dir / f"bc-{cache_key}"
    work_dir.mkdir(parents=True, exist_ok=True)
    input_path = work_dir / "input.txt"
    output_path = work_dir / "output.csv"

    input_text = _build_input_file(
        data_dir=data_dir,
        output_path=str(output_path),
        txlat=txlat,
        txlng=txlng,
        rxlat=rxlat,
        rxlng=rxlng,
        year=year,
        month=month,
        ssn=ssn,
        power_w=power_w,
        mode=mode,
        short_path=short_path,
    )
    input_path.write_text(input_text, encoding="utf-8")

    result = run_prop_command(cli_path=cli_path, args=["-c", str(input_path), str(output_path)], timeout=120.0)
    if result.returncode != 0:
        return None

    parsed = _parse_iturhfprop_csv(output_path)
    if not parsed:
        return None

    utc_hour = utc_hour % 24
    def _rel_for_hour(hour: int) -> List[float]:
        values = []
        for freq in BAND_FREQS_MHZ:
            rel = parsed.get((hour, freq))
            if rel is None:
                rel = 0.0
            values.append(max(0.0, min(1.0, rel)))
        return values

    hour_values = _rel_for_hour(utc_hour)
    rel_line = ",".join(f"{v:.2f}" for v in hour_values)

    mode_name = {
        38: "SSB",
        49: "AM",
        19: "CW",
        22: "RTTY",
        3: "WSPR",
        13: "FT8",
        17: "FT4",
    }.get(mode, "SSB")
    path_name = "SP" if short_path else "LP"
    config_line = f"{power_w}W,{mode_name},TOA>3,{path_name},S={ssn}"

    lines = [rel_line, config_line]
    for hour in range(1, 25):
        rels = _rel_for_hour(hour % 24)
        line = f"{hour % 24} " + ",".join(f"{v:.2f}" for v in rels)
        if hour == 24:
            line = f"0 " + ",".join(f"{v:.2f}" for v in rels)
        lines.append(line)

    output = "\n".join(lines) + "\n"
    _write_cached(cache_path, output)
    return output
