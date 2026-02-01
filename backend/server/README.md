# HamClock Backend (Flask)

This is a starter Flask backend that serves HamClock endpoints from a local
`DATA_ROOT` directory. By default it points at `backend/gold` so you can test
against the captured reference responses.

## Quick Start

```bash
python -m venv .venv
. .venv/bin/activate
pip install -r backend/server/requirements.txt

export HAMCLOCK_DATA_ROOT=/home/brian/repos/ESPHamClock/backend/gold
export HAMCLOCK_ENABLE_SCHEDULER=1
export HAMCLOCK_PORT=8080
export HAMCLOCK_FETCHER_TIMEOUT=15
export HAMCLOCK_FETCHER_UA="HamClockBackend/0.1 (+https://example.invalid)"
export HAMCLOCK_GEOLOC_PROVIDER=auto
export HAMCLOCK_BASE_PATH=/ham/HamClock
python -m backend.server.app
```

Or use CLI flags:
```bash
python -m backend.server.app \
  --data-root /home/brian/repos/ESPHamClock/backend/gold \
  --enable-scheduler \
  --port 8080 \
  --log-level INFO
```

Test:
```bash
curl -v "http://localhost:8080/ssn/ssn-31.txt"
curl -v "http://localhost:8080/fetchIPGeoloc.pl?IP=8.8.8.8"
```

## Environment Variables

- `HAMCLOCK_DATA_ROOT` (default: `backend/gold`)
- `HAMCLOCK_ENABLE_SCHEDULER` (default: `0`)
- `HAMCLOCK_LOG_LEVEL` (default: `INFO`)
- `HAMCLOCK_STRICT_MISSING` (default: `0`) return 503 for missing files
- `HAMCLOCK_PORT` (default: `8080`)
- `HAMCLOCK_FETCHER_TIMEOUT` (default: `15`)
- `HAMCLOCK_FETCHER_UA` (default: `HamClockBackend/0.1 (+https://example.invalid)`)
- `HAMCLOCK_GEOLOC_PROVIDER` (default: `file`, use `auto` for live lookup)
- `HAMCLOCK_GEOLOC_TIMEOUT` (default: `5`)
- `HAMCLOCK_BASE_PATH` (default: `/ham/HamClock`)
- `HAMCLOCK_RSS_FEEDS` (default: built-in list; eHam URL `https://www.eham.net/rss/news` currently returns 403)
- `HAMCLOCK_GEOCODE_CACHE_DAYS` (default: `30`)
- `HAMCLOCK_GEOCODE_PROVIDER` (default: `nominatim`)
- `HAMCLOCK_GEOCODE_BASE_URL` (default: `https://nominatim.openstreetmap.org/reverse`)
- `HAMCLOCK_GEOCODE_EMAIL` (default: unset, recommended for Nominatim usage)
- `HAMCLOCK_PROP_ENABLED` (default: `0`)
- `HAMCLOCK_PROP_ENGINE` (default: `iturhfprop`)
- `HAMCLOCK_PROP_CLI_PATH` (default: unset)
- `HAMCLOCK_PROP_CACHE_DIR` (default: `./prop-cache`)
- `HAMCLOCK_PROP_DATA_DIR` (default: auto-detects snap data dir)
- `HAMCLOCK_FALLBACK_ENABLED` (default: `0`)
- `HAMCLOCK_FALLBACK_DIR` (default: `./fallback`)
- `HAMCLOCK_FALLBACK_BASE_URL` (default: `http://clearskyinstitute.com`)
- `HAMCLOCK_FALLBACK_LOG_FILE` (default: unset)
- `HAMCLOCK_FALLBACK_REDIRECT` (default: `0`)

## Phase 1 Fetchers

When the scheduler is enabled, Phase 1 refresh jobs run automatically:

- Cities (`cities2.txt`) from GeoNames (monthly)
- Prefix/CTY (`cty/cty_wt_mod-ll-dxcc.txt`) from country-files (monthly)
- Satellites (`esats/esats.txt`) from CelesTrak (every 3 hours)
- Version (`version.txt`) from `HAMCLOCK_VERSION` env (every 12 hours)

Set `HAMCLOCK_VERSION` and optionally `HAMCLOCK_VERSION_INFO` to control `version.txt`.

## Phase 2 Fetchers (Space Weather)

When the scheduler is enabled, Phase 2 refresh jobs run automatically:

- SSN (`ssn/ssn-31.txt`, `ssn/ssn-history.txt`)
- Solar flux (`solar-flux/solarflux-99.txt`, `solar-flux/solarflux-history.txt`)
- Kp index (`geomag/kindex.txt`)
- X-ray flux (`xray/xray.txt`)
- Solar wind (`solar-wind/swind-24hr.txt`)
- IMF Bz/Bt (`Bz/Bz.txt`)
- NOAA scales (`NOAASpaceWX/noaaswx.txt`)
- Aurora (`aurora/aurora.txt`)
- Dst (`dst/dst.txt`)
- D-RAP stats (`drap/stats.txt`)

## Phase 3 Fetchers (Amateur Radio Data)

When the scheduler is enabled, Phase 3 refresh jobs run automatically:

- ONTA (POTA only) (`ONTA/onta.txt`)
- RSS headlines (`RSS/web15rss.txt`)

SOTA support remains disabled (use fallback if needed).

## Phase 4 Fetchers (Weather)

When the scheduler is enabled, Phase 4 refresh jobs run automatically:

- World weather grid (`worldwx/wx.txt`)

`/wx.pl` uses Open-Meteo live when `lat`/`lng` are provided; otherwise it falls back to local files.

## Client Redirect Proxy (for testing 3xx Location responses)

HamClock does not follow HTTP redirects. If you want to test Location-based redirects,
run the local Python proxy that follows redirects before returning the body to HamClock.

Example:
```
python -m venv .venv
. .venv/bin/activate
pip install -r backend/client-redirect/requirements.txt
python backend/client-redirect/redirect_proxy.py --backend http://127.0.0.1:8123 --listen-port 8088
```

Then start HamClock with:
```
-b 127.0.0.1:8088
```

## Propagation Engine Setup (Phase 5)

We recommend using **ITURHFProp** on Ubuntu because it’s open source and can be
driven from a CLI, which keeps the backend simple. It is **not** packaged in the
default Ubuntu apt repositories; use the snap or build from source instead.

Suggested steps (snap):

1) Download the snap package (from the ITU/Proppy distribution)
```
iturhfprop_0.1_amd64.snap
```

2) Install the snap (unsigned)
```
sudo snap install --dangerous iturhfprop_0.1_amd64.snap
```

3) Configure HamClock backend to use it
```
export HAMCLOCK_PROP_ENABLED=1
export HAMCLOCK_PROP_ENGINE=iturhfprop
export HAMCLOCK_PROP_CLI_PATH=$(which iturhfprop)
export HAMCLOCK_PROP_CACHE_DIR=/var/lib/hamclock/prop-cache
export HAMCLOCK_PROP_DATA_DIR=/path/to/iturhfprop/data
```

Data files:
- When running from the snap, ITURHFProp data files are at:
```
/snap/iturhfprop/current/usr/share/iturhfprop/data/
```

Alternative (build from source):
- ITU-R HF source repo:
```
https://github.com/ITU-R-Study-Group-3/ITU-R-HF
```

Notes:
- The backend will shell out to the CLI when implementing `/fetchBandConditions.pl`
  and VOACAP map endpoints.
- You can choose a different engine later (e.g., VOACAP) by changing
  `HAMCLOCK_PROP_ENGINE` and `HAMCLOCK_PROP_CLI_PATH`.
- If you use a local ITURHFProp binary with adjacent `libp372.so`/`libp533.so`,
  the backend will set `LD_LIBRARY_PATH` to include the binary directory when
  invoking it.

## CLI Flags

```
--data-root PATH
--port PORT
--enable-scheduler
--log-level LEVEL
--base-path PATH
--refresh-on-start
--refresh-cty-only
--update-x-on-start NAME
--hamclock-version VERSION
--hamclock-version-info INFO
--clearskyinstitute-fallback
--fallback-dir PATH
--fallback-base-url URL
--fallback-log-file PATH
--fallback-redirect
--fetcher-timeout SECONDS
--fetcher-ua STRING
--geoloc-provider NAME
--geoloc-timeout SECONDS
--strict-missing
```

Single-update names for `--update-x-on-start`:
```
cities, cty, esats, version, ssn, ssn_history, solar_flux, solar_flux_history,
kindex, xray, solar_wind, bz, noaa_scales, aurora, dst, drap, onta, rss, worldwx
```

## Nginx Reverse Proxy (example)

Create a server block like:

```nginx
upstream hamclock_backend {
    server 127.0.0.1:8080;
}

server {
    listen 80;
    server_name hamclock.local;

    location / {
        proxy_pass http://hamclock_backend;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    }

    # Optional: serve map/SDO assets directly from disk
    # location /maps/ {
    #     alias /var/lib/hamclock/maps/;
    # }
    # location /SDO/ {
    #     alias /var/lib/hamclock/SDO/;
    # }
}
```

## Notes

- The scheduler is currently a placeholder heartbeat. Add real data refresh
  tasks in `backend/server/tasks/` and register them in `get_jobs()`.
- Dynamic endpoints currently return sample data from `backend/gold`.
