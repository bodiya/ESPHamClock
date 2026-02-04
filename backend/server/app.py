from __future__ import annotations

import argparse
import logging
import sys
from datetime import datetime, timezone
from email.utils import formatdate
from pathlib import Path
from typing import Optional

from flask import Flask, Response, request

from .config import default_config
from .scheduler import start_scheduler
from .services.geoloc import lookup_ip
from .services.spots import fetch_pskreporter as psk_fetcher, fetch_wspr as wspr_fetcher, fetch_rbn as rbn_fetcher
from .services.propagation import compute_band_conditions
from .storage import SafePathError, read_binary_and_mtime, read_text_and_mtime
from .tasks import build_context
from .fetchers.phase1 import update_cty, update_cities, update_esats, update_version
from .fetchers.phase4 import update_wx
from .datasources import get_registry, assess_derived_text, run_derive, run_health_checks, run_ingest_then_derive
from .fallback import fetch_with_cache, setup_fallback_logging


TEXT_CONTENT_TYPE = "text/plain; charset=ISO-8859-1"
BINARY_CONTENT_TYPE = "image/bmp; charset=ISO-8859-1"


app = Flask(__name__)
app.config.update(default_config())
log = logging.getLogger("hamclock-backend")


BASE_TEXT_ROUTES = {
    "/ssn/ssn-31.txt": "ssn/ssn-31.txt",
    "/ssn/ssn-history.txt": "ssn/ssn-history.txt",
    "/solar-flux/solarflux-99.txt": "solar-flux/solarflux-99.txt",
    "/solar-flux/solarflux-history.txt": "solar-flux/solarflux-history.txt",
    "/geomag/kindex.txt": "geomag/kindex.txt",
    "/xray/xray.txt": "xray/xray.txt",
    "/solar-wind/swind-24hr.txt": "solar-wind/swind-24hr.txt",
    "/Bz/Bz.txt": "Bz/Bz.txt",
    "/NOAASpaceWX/noaaswx.txt": "NOAASpaceWX/noaaswx.txt",
    "/NOAASpaceWX/rank2_coeffs.txt": "NOAASpaceWX/rank2_coeffs.txt",
    "/aurora/aurora.txt": "aurora/aurora.txt",
    "/dst/dst.txt": "dst/dst.txt",
    "/drap/stats.txt": "drap/stats.txt",
    "/cty/cty_wt_mod-ll-dxcc.txt": "cty/cty_wt_mod-ll-dxcc.txt",
    "/esats/esats.txt": "esats/esats.txt",
    "/ONTA/onta.txt": "ONTA/onta.txt",
    "/contests/contests311.txt": "contests/contests311.txt",
    "/dxpeds/dxpeditions.txt": "dxpeds/dxpeditions.txt",
    "/RSS/web15rss.pl": "RSS/web15rss.txt",
    "/RSS/web15rss.txt": "RSS/web15rss.txt",
    "/worldwx/wx.txt": "worldwx/wx.txt",
    "/cities2.txt": "cities2.txt",
    "/version.pl": "version.txt",
}

BASE_BINARY_ROUTES = {
    "/fetchVOACAPArea.pl": "fetchVOACAPArea.z",
    "/fetchVOACAP-MUF.pl": "fetchVOACAP-MUF.z",
    "/fetchVOACAP-TOA.pl": "fetchVOACAP-TOA.z",
}


def _http_date(epoch_seconds: float) -> str:
    return formatdate(epoch_seconds, usegmt=True)


def _missing_response() -> Response:
    if app.config["STRICT_MISSING"]:
        return Response("", status=503, mimetype=TEXT_CONTENT_TYPE)
    return Response("", status=200, mimetype=TEXT_CONTENT_TYPE)


def _fallback_redirect_response() -> Response:
    base = app.config.get("FALLBACK_BASE_URL", "http://clearskyinstitute.com")
    url = f"{base}{request.full_path}"
    return Response("", status=302, headers={"Location": url})


def _make_text_response(text: str, mtime: Optional[float]) -> Response:
    resp = Response(text, status=200, mimetype=TEXT_CONTENT_TYPE)
    if mtime is not None:
        resp.headers["Last-Modified"] = _http_date(mtime)
    return resp


def _make_binary_response(data: bytes, mtime: Optional[float]) -> Response:
    resp = Response(data, status=200, mimetype=BINARY_CONTENT_TYPE)
    if mtime is not None:
        resp.headers["Last-Modified"] = _http_date(mtime)
    return resp


def _serve_text_file(rel_path: str) -> Response:
    try:
        text, mtime = read_text_and_mtime(app.config["DATA_ROOT"], rel_path, encoding="utf-8")
    except SafePathError:
        return Response("", status=404)
    if text is None:
        log.warning("Missing text file: %s", rel_path)
        if app.config.get("FALLBACK_REDIRECT"):
            return _fallback_redirect_response()
        if app.config.get("FALLBACK_ENABLED"):
            resp = fetch_with_cache(
                fallback_dir=app.config["FALLBACK_DIR"],
                base_url=app.config["FALLBACK_BASE_URL"],
                timeout=app.config.get("FETCHER_TIMEOUT", 15.0),
                max_age_seconds=0.0,
            )
            if resp is not None:
                return resp
        return _missing_response()
    ok, reason = assess_derived_text(build_context(app), rel_path, text, mtime)
    if not ok:
        log.warning("Derived text invalid for %s: %s", rel_path, reason)
        if app.config.get("FALLBACK_REDIRECT"):
            return _fallback_redirect_response()
        if app.config.get("FALLBACK_ENABLED"):
            resp = fetch_with_cache(
                fallback_dir=app.config["FALLBACK_DIR"],
                base_url=app.config["FALLBACK_BASE_URL"],
                timeout=app.config.get("FETCHER_TIMEOUT", 15.0),
                max_age_seconds=0.0,
            )
            if resp is not None:
                return resp
        return _missing_response()
    return _make_text_response(text, mtime)


def _serve_binary_file(rel_path: str) -> Response:
    try:
        data, mtime = read_binary_and_mtime(app.config["DATA_ROOT"], rel_path)
    except SafePathError:
        return Response("", status=404)
    if data is None or len(data) == 0:
        log.warning("Missing binary file: %s", rel_path)
        if app.config.get("FALLBACK_REDIRECT"):
            return _fallback_redirect_response()
        if app.config.get("FALLBACK_ENABLED"):
            resp = fetch_with_cache(
                fallback_dir=app.config["FALLBACK_DIR"],
                base_url=app.config["FALLBACK_BASE_URL"],
                timeout=app.config.get("FETCHER_TIMEOUT", 15.0),
                max_age_seconds=0.0,
            )
            if resp is not None:
                return resp
        return _missing_response()
    return _make_binary_response(data, mtime)


def _latest_ssn(data_root: Path) -> int:
    path = data_root / "ssn" / "ssn-31.txt"
    if not path.exists():
        return 0
    try:
        lines = [line.strip() for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
        if not lines:
            return 0
        last = lines[-1].split()
        if last:
            return int(float(last[-1]))
    except Exception:
        return 0
    return 0


@app.before_request
def _log_request() -> None:
    if log.isEnabledFor(logging.DEBUG):
        headers = "\n".join(f"{k}: {v}" for k, v in request.headers.items())
        log.debug("Request %s %s\n%s", request.method, request.full_path, headers)
    else:
        log.debug("%s %s", request.method, request.full_path)


@app.errorhandler(404)
def handle_not_found(error) -> Response:
    if app.config.get("FALLBACK_REDIRECT"):
        return _fallback_redirect_response()
    if app.config.get("FALLBACK_ENABLED"):
        resp = fetch_with_cache(
            fallback_dir=app.config["FALLBACK_DIR"],
            base_url=app.config["FALLBACK_BASE_URL"],
            timeout=app.config.get("FETCHER_TIMEOUT", 15.0),
            max_age_seconds=0.0,
        )
        if resp is not None:
            return resp
    return Response("", status=404)


def _register_static_route(route: str, rel_path: str, binary: bool) -> None:
    endpoint = f"static_{route.strip('/').replace('/', '_').replace('.', '_')}"
    if binary:
        app.add_url_rule(route, endpoint=endpoint, view_func=lambda rel_path=rel_path: _serve_binary_file(rel_path))
    else:
        app.add_url_rule(route, endpoint=endpoint, view_func=lambda rel_path=rel_path: _serve_text_file(rel_path))


for route, rel_path in BASE_TEXT_ROUTES.items():
    _register_static_route(route, rel_path, binary=False)

for route, rel_path in BASE_BINARY_ROUTES.items():
    _register_static_route(route, rel_path, binary=True)


@app.get("/fetchBandConditions.pl")
def fetch_band_conditions() -> Response:
    ctx = build_context(app)
    if ctx.prop_enabled and ctx.prop_cli_path and ctx.prop_data_dir:
        try:
            year = int(request.args.get("YEAR", "2024"))
            month = int(request.args.get("MONTH", "1"))
            rxlat = float(request.args.get("RXLAT", "0"))
            rxlng = float(request.args.get("RXLNG", "0"))
            txlat = float(request.args.get("TXLAT", "0"))
            txlng = float(request.args.get("TXLNG", "0"))
            utc = int(float(request.args.get("UTC", "0")))
            path_flag = request.args.get("PATH", "0")
            power = int(float(request.args.get("POW", "100")))
            mode = int(float(request.args.get("MODE", "38")))
        except ValueError:
            year = month = utc = power = mode = 0
            rxlat = rxlng = txlat = txlng = 0.0
            path_flag = "0"

        short_path = str(path_flag).strip() in ("0", "1", "SP", "sp", "short")
        ssn = _latest_ssn(ctx.data_root)
        content = compute_band_conditions(
            query=request.query_string.decode("utf-8", errors="replace"),
            cache_dir=ctx.prop_cache_dir or ctx.data_root / "prop-cache",
            cli_path=ctx.prop_cli_path,
            data_dir=ctx.prop_data_dir,
            txlat=txlat,
            txlng=txlng,
            rxlat=rxlat,
            rxlng=rxlng,
            year=year,
            month=month,
            utc_hour=utc,
            ssn=ssn,
            power_w=power,
            mode=mode,
            short_path=short_path,
        )
        if content:
            return _make_text_response(content, None)

    path_flag = request.args.get("PATH", "0")
    is_long = str(path_flag).strip() in ("2", "LP", "lp", "long")
    rel_path = "fetchBandConditions_long.txt" if is_long else "fetchBandConditions.txt"
    return _serve_text_file(rel_path)


@app.get("/fetchIPGeoloc.pl")
def fetch_ip_geoloc() -> Response:
    ip = request.args.get("IP") or request.remote_addr or "0.0.0.0"
    provider = app.config["GEOLOC_PROVIDER"]
    if provider != "file":
        result = lookup_ip(
            ip,
            provider=provider,
            timeout=app.config["GEOLOC_TIMEOUT"],
            user_agent=app.config["FETCHER_USER_AGENT"],
        )
        if result is not None:
            lat, lng, credit = result
            payload = f"LAT={lat}\nLNG={lng}\nIP={ip}\nCREDIT={credit}\n"
            return _make_text_response(payload, None)

    text, mtime = read_text_and_mtime(app.config["DATA_ROOT"], "fetchIPGeoloc.txt", encoding="utf-8")
    if text is None:
        log.warning("Missing text file: fetchIPGeoloc.txt")
        if app.config.get("FALLBACK_REDIRECT"):
            return _fallback_redirect_response()
        if app.config.get("FALLBACK_ENABLED"):
            resp = fetch_with_cache(
                fallback_dir=app.config["FALLBACK_DIR"],
                base_url=app.config["FALLBACK_BASE_URL"],
                timeout=app.config.get("FETCHER_TIMEOUT", 15.0),
                max_age_seconds=0.0,
            )
            if resp is not None:
                return resp
        return _missing_response()

    lines = []
    for line in text.splitlines():
        if line.startswith("IP="):
            lines.append(f"IP={ip}")
        else:
            lines.append(line)
    return _make_text_response("\n".join(lines) + "\n", mtime)


@app.get("/wx.pl")
def fetch_weather() -> Response:
    is_de = request.args.get("is_de", "1")
    lat = request.args.get("lat")
    lng = request.args.get("lng")
    if lat and lng:
        try:
            lat_f = float(lat)
            lng_f = float(lng)
        except ValueError:
            lat_f = None
            lng_f = None
        if lat_f is not None and lng_f is not None:
            ctx = build_context(app)
            content = update_wx(ctx, is_de == "1", lat_f, lng_f)
            if content:
                return _make_text_response(content, None)
    rel_path = "wx_de.txt" if is_de == "1" else "wx_dx.txt"
    return _serve_text_file(rel_path)


@app.get("/fetchPSKReporter.pl")
def fetch_pskreporter() -> Response:
    maxage = int(request.args.get("maxage", "3600"))
    query_type = None
    query_value = None
    for key in ("bygrid", "ofgrid", "bycall", "ofcall"):
        if key in request.args:
            query_type = key
            query_value = request.args.get(key)
            break

    if query_type and query_value:
        content = psk_fetcher(
            data_root=app.config["DATA_ROOT"],
            user_agent=app.config["FETCHER_USER_AGENT"],
            timeout=app.config.get("FETCHER_TIMEOUT", 15.0),
            max_age=maxage,
            query_type=query_type,
            query_value=query_value,
        )
        if content:
            return _make_text_response(content, None)

    if any(key.startswith("of") for key in request.args.keys()):
        return _serve_text_file("fetchPSKReporter_ofgrid.txt")
    return _serve_text_file("fetchPSKReporter_bygrid.txt")


@app.get("/fetchWSPR.pl")
def fetch_wspr() -> Response:
    maxage = int(request.args.get("maxage", "3600"))
    query_type = None
    query_value = None
    for key in ("bygrid", "ofgrid", "bycall", "ofcall"):
        if key in request.args:
            query_type = key
            query_value = request.args.get(key)
            break

    if query_type and query_value:
        content = wspr_fetcher(
            data_root=app.config["DATA_ROOT"],
            user_agent=app.config["FETCHER_USER_AGENT"],
            timeout=app.config.get("FETCHER_TIMEOUT", 15.0),
            max_age=maxage,
            query_type=query_type,
            query_value=query_value,
        )
        if content:
            return _make_text_response(content, None)

    return _serve_text_file("fetchWSPR_bygrid.txt")


@app.get("/fetchRBN.pl")
def fetch_rbn() -> Response:
    maxage = int(request.args.get("maxage", "3600"))
    query_type = None
    query_value = None
    for key in ("bygrid", "ofgrid", "bycall", "ofcall"):
        if key in request.args:
            query_type = key
            query_value = request.args.get(key)
            break

    if query_type and query_value:
        content = rbn_fetcher(
            data_root=app.config["DATA_ROOT"],
            user_agent=app.config["FETCHER_USER_AGENT"],
            timeout=app.config.get("FETCHER_TIMEOUT", 15.0),
            max_age=maxage,
            query_type=query_type,
            query_value=query_value,
        )
        if content:
            return _make_text_response(content, None)

    return _serve_text_file("fetchRBN_bygrid.txt")


@app.get("/maps/<path:filename>")
def fetch_map_tile(filename: str) -> Response:
    rel_path = str(Path("maps") / filename)
    return _serve_binary_file(rel_path)


@app.get("/SDO/<path:filename>")
def fetch_sdo(filename: str) -> Response:
    rel_path = str(Path("SDO") / filename)
    return _serve_binary_file(rel_path)


@app.get("/healthz")
def healthz() -> Response:
    payload = f"ok {datetime.now(timezone.utc).isoformat()}\n"
    return Response(payload, status=200, mimetype=TEXT_CONTENT_TYPE)


def _normalize_base_path(path: str) -> str:
    if not path:
        return ""
    if not path.startswith("/"):
        path = f"/{path}"
    return path.rstrip("/")


def register_base_path_aliases() -> None:
    base_path = _normalize_base_path(app.config.get("BASE_PATH", ""))
    if not base_path:
        return

    for route, rel_path in BASE_TEXT_ROUTES.items():
        _register_static_route(f"{base_path}{route}", rel_path, binary=False)
    for route, rel_path in BASE_BINARY_ROUTES.items():
        _register_static_route(f"{base_path}{route}", rel_path, binary=True)

    app.add_url_rule(f"{base_path}/fetchBandConditions.pl", endpoint="prefetch_band", view_func=fetch_band_conditions)
    app.add_url_rule(f"{base_path}/fetchIPGeoloc.pl", endpoint="prefetch_ip", view_func=fetch_ip_geoloc)
    app.add_url_rule(f"{base_path}/wx.pl", endpoint="prefetch_wx", view_func=fetch_weather)
    app.add_url_rule(f"{base_path}/fetchPSKReporter.pl", endpoint="prefetch_psk", view_func=fetch_pskreporter)
    app.add_url_rule(f"{base_path}/fetchWSPR.pl", endpoint="prefetch_wspr", view_func=fetch_wspr)
    app.add_url_rule(f"{base_path}/fetchRBN.pl", endpoint="prefetch_rbn", view_func=fetch_rbn)
    app.add_url_rule(f"{base_path}/maps/<path:filename>", endpoint="prefetch_maps", view_func=fetch_map_tile)
    app.add_url_rule(f"{base_path}/SDO/<path:filename>", endpoint="prefetch_sdo", view_func=fetch_sdo)
    app.add_url_rule(f"{base_path}/healthz", endpoint="prefetch_healthz", view_func=healthz)

def init_scheduler() -> None:
    if app.config["ENABLE_SCHEDULER"]:
        start_scheduler(app)


def refresh_on_start() -> None:
    ctx = build_context(app)
    registry = get_registry()
    for source in registry.values():
        if source.ingest:
            try:
                ok = run_ingest_then_derive(ctx, source)
                log.info("Startup ingest+derive %s completed: %s", source.name, ok)
            except Exception as exc:  # noqa: BLE001
                log.warning("Startup ingest+derive %s failed: %s", source.name, exc)
        elif source.derive:
            try:
                ok = run_derive(ctx, source)
                log.info("Startup derive %s completed: %s", source.name, ok)
            except Exception as exc:  # noqa: BLE001
                log.warning("Startup derive %s failed: %s", source.name, exc)


def _update_once(name: str) -> bool:
    ctx = build_context(app)
    registry = get_registry()
    phase = None
    if ":" in name:
        name, phase = name.split(":", 1)
    source = registry.get(name)
    if not source:
        log.warning("Unknown update source: %s", name)
        return False
    ok = True
    if phase in (None, "ingest"):
        if source.ingest:
            ok = bool(source.ingest(ctx)) and ok
        elif phase == "ingest":
            log.warning("Source %s has no ingest phase", name)
            return False
    if phase in (None, "derive"):
        if source.derive:
            ok = bool(run_derive(ctx, source)) and ok
        elif phase == "derive":
            log.warning("Source %s has no derive phase", name)
            return False
    return ok


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="HamClock backend server")
    parser.add_argument("--data-root", help="Path to data root directory")
    parser.add_argument("--port", type=int, help="Port to bind (default: 8080)")
    parser.add_argument("--enable-scheduler", action="store_true", help="Enable APScheduler")
    parser.add_argument("--log-level", help="Logging level (default: INFO)")
    parser.add_argument("--base-path", help="Optional base URL path, e.g. /ham/HamClock")
    parser.add_argument("--refresh-on-start", action="store_true", help="Run Phase 1 fetchers before serving")
    parser.add_argument("--refresh-cty-only", action="store_true", help="Run only CTY refresh before serving")
    parser.add_argument(
        "--update-x-on-start",
        help="Update a single datasource (e.g. ssn, xray, aurora) or name:ingest/name:derive",
    )
    parser.add_argument("--hamclock-version", help="Version string for version.txt")
    parser.add_argument("--hamclock-version-info", help="Optional second line for version.txt")
    parser.add_argument("--clearskyinstitute-fallback", action="store_true", help="Proxy missing endpoints to clearskyinstitute.com and cache results")
    parser.add_argument("--fallback-dir", help="Fallback cache directory (default: ./fallback)")
    parser.add_argument("--fallback-base-url", help="Fallback base URL (default: http://clearskyinstitute.com)")
    parser.add_argument("--fallback-log-file", help="Log fallback requests/responses to this file")
    parser.add_argument("--fallback-redirect", action="store_true", help="Return 302 Location to fallback base URL")
    parser.add_argument("--fetcher-timeout", type=float, help="Fetcher timeout in seconds")
    parser.add_argument("--fetcher-ua", help="User-Agent string for fetchers")
    parser.add_argument("--geoloc-provider", help="Geoloc provider (file, auto, ip-api, ipapi, ipwhois)")
    parser.add_argument("--geoloc-timeout", type=float, help="Geoloc timeout in seconds")
    parser.add_argument("--open-meteo-base-url", help="Open-Meteo base URL (default: https://api.open-meteo.com/v1/forecast)")
    parser.add_argument("--open-meteo-api-key", help="Open-Meteo API key (optional)")
    parser.add_argument("--health-check-now", action="store_true", help="Run datasource health check and exit")
    parser.add_argument(
        "--strict-missing",
        action="store_true",
        help="Return 503 for missing files instead of empty 200",
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = _parse_args()
    if args.data_root:
        app.config["DATA_ROOT"] = Path(args.data_root).expanduser().resolve()
    if args.port:
        app.config["PORT"] = args.port
    if args.enable_scheduler:
        app.config["ENABLE_SCHEDULER"] = True
    if args.log_level:
        app.config["LOG_LEVEL"] = args.log_level.upper()
    if args.base_path:
        app.config["BASE_PATH"] = args.base_path
    if args.clearskyinstitute_fallback:
        app.config["FALLBACK_ENABLED"] = True
    if args.fallback_dir:
        app.config["FALLBACK_DIR"] = Path(args.fallback_dir).expanduser().resolve()
    if args.fallback_base_url:
        app.config["FALLBACK_BASE_URL"] = args.fallback_base_url
    if args.fallback_log_file:
        app.config["FALLBACK_LOG_FILE"] = args.fallback_log_file
    if args.fallback_redirect:
        app.config["FALLBACK_REDIRECT"] = True
    if args.hamclock_version:
        app.config["HAMCLOCK_VERSION"] = args.hamclock_version
    if args.hamclock_version_info:
        app.config["HAMCLOCK_VERSION_INFO"] = args.hamclock_version_info
    if args.fetcher_timeout is not None:
        app.config["FETCHER_TIMEOUT"] = args.fetcher_timeout
    if args.fetcher_ua:
        app.config["FETCHER_USER_AGENT"] = args.fetcher_ua
    if args.geoloc_provider:
        app.config["GEOLOC_PROVIDER"] = args.geoloc_provider
    if args.geoloc_timeout is not None:
        app.config["GEOLOC_TIMEOUT"] = args.geoloc_timeout
    if args.open_meteo_base_url:
        app.config["OPEN_METEO_BASE_URL"] = args.open_meteo_base_url
    if args.open_meteo_api_key:
        app.config["OPEN_METEO_API_KEY"] = args.open_meteo_api_key
    if args.strict_missing:
        app.config["STRICT_MISSING"] = True

    logging.basicConfig(level=app.config["LOG_LEVEL"])
    setup_fallback_logging(app.config.get("FALLBACK_LOG_FILE"))
    if args.health_check_now:
        ctx = build_context(app)
        ok = run_health_checks(ctx)
        sys.exit(0 if ok else 1)
    register_base_path_aliases()
    if args.update_x_on_start:
        _update_once(args.update_x_on_start)
    elif args.refresh_cty_only:
        ctx = build_context(app)
        update_cty(ctx)
    elif args.refresh_on_start:
        refresh_on_start()
    init_scheduler()
    app.run(host="0.0.0.0", port=app.config["PORT"])
