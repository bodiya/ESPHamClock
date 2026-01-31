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

## CLI Flags

```
--data-root PATH
--port PORT
--enable-scheduler
--log-level LEVEL
--strict-missing
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
