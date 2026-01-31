from __future__ import annotations

from pathlib import Path
from typing import Optional, Tuple


class SafePathError(RuntimeError):
    pass


def resolve_under(root: Path, rel_path: str) -> Path:
    candidate = (root / rel_path).resolve()
    if root not in candidate.parents and candidate != root:
        raise SafePathError(f"Path escapes data root: {rel_path}")
    return candidate


def read_text(root: Path, rel_path: str, encoding: str = "utf-8") -> Optional[str]:
    path = resolve_under(root, rel_path)
    if not path.exists():
        return None
    return path.read_text(encoding=encoding)


def read_binary(root: Path, rel_path: str) -> Optional[bytes]:
    path = resolve_under(root, rel_path)
    if not path.exists():
        return None
    return path.read_bytes()


def read_text_and_mtime(root: Path, rel_path: str, encoding: str = "utf-8") -> Tuple[Optional[str], Optional[float]]:
    path = resolve_under(root, rel_path)
    if not path.exists():
        return None, None
    return path.read_text(encoding=encoding), path.stat().st_mtime


def read_binary_and_mtime(root: Path, rel_path: str) -> Tuple[Optional[bytes], Optional[float]]:
    path = resolve_under(root, rel_path)
    if not path.exists():
        return None, None
    return path.read_bytes(), path.stat().st_mtime
