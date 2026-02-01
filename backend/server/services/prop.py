from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Dict, List, Optional


def _build_ld_library_path(cli_path: str, base_env: Optional[Dict[str, str]] = None) -> Dict[str, str]:
    env = dict(base_env or os.environ)
    lib_dir = str(Path(cli_path).resolve().parent)
    existing = env.get("LD_LIBRARY_PATH", "")
    if existing:
        if lib_dir not in existing.split(":"):
            env["LD_LIBRARY_PATH"] = f"{lib_dir}:{existing}"
    else:
        env["LD_LIBRARY_PATH"] = lib_dir
    return env


def run_prop_command(
    *,
    cli_path: str,
    args: List[str],
    timeout: float = 60.0,
    cwd: Optional[str] = None,
    env_extra: Optional[Dict[str, str]] = None,
) -> subprocess.CompletedProcess[str]:
    env = _build_ld_library_path(cli_path, env_extra)
    cmd = [cli_path, *args]
    return subprocess.run(
        cmd,
        cwd=cwd,
        env=env,
        text=True,
        capture_output=True,
        timeout=timeout,
        check=False,
    )
