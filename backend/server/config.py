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
        "BASE_PATH": os.environ.get("HAMCLOCK_BASE_PATH", "/ham/HamClock"),
        "FETCHER_USER_AGENT": os.environ.get(
            "HAMCLOCK_FETCHER_UA", "HamClockBackend/0.1 (+https://example.invalid)"
        ),
        "FETCHER_TIMEOUT": float(os.environ.get("HAMCLOCK_FETCHER_TIMEOUT", "15")),
        "GEOLOC_PROVIDER": os.environ.get("HAMCLOCK_GEOLOC_PROVIDER", "file"),
        "GEOLOC_TIMEOUT": float(os.environ.get("HAMCLOCK_GEOLOC_TIMEOUT", "5")),
        "HAMCLOCK_VERSION": os.environ.get("HAMCLOCK_VERSION"),
        "HAMCLOCK_VERSION_INFO": os.environ.get("HAMCLOCK_VERSION_INFO"),
        "FALLBACK_ENABLED": os.environ.get("HAMCLOCK_FALLBACK_ENABLED", "0") == "1",
        "FALLBACK_DIR": Path(os.environ.get("HAMCLOCK_FALLBACK_DIR", "./fallback"))
        .expanduser()
        .resolve(),
        "FALLBACK_BASE_URL": os.environ.get("HAMCLOCK_FALLBACK_BASE_URL", "http://clearskyinstitute.com"),
        "FALLBACK_LOG_FILE": os.environ.get("HAMCLOCK_FALLBACK_LOG_FILE"),
        "FALLBACK_REDIRECT": os.environ.get("HAMCLOCK_FALLBACK_REDIRECT", "0") == "1",
        "RSS_FEEDS": [
            url.strip()
            for url in os.environ.get(
                "HAMCLOCK_RSS_FEEDS",
                (
                    "http://www.arrl.org/arrl.rss,"
                    "https://www.dx-world.net/feed/,"
                    "https://forums.qrz.com/index.php?forums/news-rss.15/index.rss,"
                    "https://www.arnewsline.org/arnewsline.xml,"
                    "https://hamweekly.com/ham-news.xml"
                ),
            ).split(",")
            if url.strip()
        ],
        "GEOCODE_CACHE_DAYS": int(os.environ.get("HAMCLOCK_GEOCODE_CACHE_DAYS", "30")),
        "GEOCODE_PROVIDER": os.environ.get("HAMCLOCK_GEOCODE_PROVIDER", "nominatim"),
        "GEOCODE_BASE_URL": os.environ.get(
            "HAMCLOCK_GEOCODE_BASE_URL", "https://nominatim.openstreetmap.org/reverse"
        ),
        "GEOCODE_EMAIL": os.environ.get("HAMCLOCK_GEOCODE_EMAIL"),
        "OPEN_METEO_BASE_URL": os.environ.get(
            "HAMCLOCK_OPEN_METEO_BASE_URL", "https://api.open-meteo.com/v1/forecast"
        ),
        "OPEN_METEO_API_KEY": os.environ.get("HAMCLOCK_OPEN_METEO_API_KEY"),
        "PROP_ENABLED": os.environ.get("HAMCLOCK_PROP_ENABLED", "0") == "1",
        "PROP_ENGINE": os.environ.get("HAMCLOCK_PROP_ENGINE", "iturhfprop"),
        "PROP_CLI_PATH": os.environ.get("HAMCLOCK_PROP_CLI_PATH"),
        "PROP_CACHE_DIR": Path(os.environ.get("HAMCLOCK_PROP_CACHE_DIR", "./prop-cache"))
        .expanduser()
        .resolve(),
        "PROP_DATA_DIR": os.environ.get("HAMCLOCK_PROP_DATA_DIR"),
    }
