import os
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent
REPO_ROOT = BASE_DIR.parent.parent
DEFAULT_DATA_ROOT = REPO_ROOT / "backend" / "gold"


def default_config() -> dict:
    return {
        "DATA_ROOT": Path(os.environ.get("HAMCLOCK_DATA_ROOT", DEFAULT_DATA_ROOT))
        .expanduser()
        .resolve(),
        "LOG_LEVEL": os.environ.get("HAMCLOCK_LOG_LEVEL", "INFO").upper(),
        "ENABLE_SCHEDULER": os.environ.get("HAMCLOCK_ENABLE_SCHEDULER", "0") == "1",
        "PORT": int(os.environ.get("HAMCLOCK_PORT", "8080")),
        "STRICT_MISSING": os.environ.get("HAMCLOCK_STRICT_MISSING", "0") == "1",
    }
