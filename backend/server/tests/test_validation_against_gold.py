from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory

from backend.server.datasources import assess_derived_text, get_registry
from backend.server.fetchers.phase1 import FetchContext


REPO_ROOT = Path(__file__).resolve().parents[3]
GOLD_ROOT = REPO_ROOT / "backend" / "gold"


def _ctx(tmp_dir: Path) -> FetchContext:
    return FetchContext(data_root=tmp_dir, timeout=5.0, user_agent="test-agent")


def test_validation_requires_gold_line_counts() -> None:
    registry = get_registry()
    with TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
        ctx = _ctx(tmp_path)
        for source in registry.values():
            for rel_path in source.derived_paths:
                gold_path = GOLD_ROOT / rel_path
                if not gold_path.exists():
                    continue
                content = gold_path.read_text(encoding="utf-8")
                target = tmp_path / rel_path
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(content, encoding="utf-8")
                ok, reason = assess_derived_text(ctx, str(rel_path), content, target.stat().st_mtime)
                assert ok, f"{rel_path} should validate against gold, got {reason}"

                lines = [line for line in content.splitlines() if line.strip()]
                if len(lines) < 2:
                    continue
                truncated = "\n".join(lines[:-1]) + "\n"
                target.write_text(truncated, encoding="utf-8")
                ok, reason = assess_derived_text(ctx, str(rel_path), truncated, target.stat().st_mtime)
                assert not ok, f"{rel_path} should fail with missing line count"
