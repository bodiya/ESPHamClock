from __future__ import annotations

import argparse
import logging
from datetime import datetime, timezone
from email.utils import formatdate
from pathlib import Path
from typing import Optional

from flask import Flask, Response, request

from .config import default_config
from .scheduler import start_scheduler
from .storage import SafePathError, read_binary_and_mtime, read_text_and_mtime


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
        return _missing_response()
    return _make_text_response(text, mtime)


def _serve_binary_file(rel_path: str) -> Response:
    try:
        data, mtime = read_binary_and_mtime(app.config["DATA_ROOT"], rel_path)
    except SafePathError:
        return Response("", status=404)
    if data is None:
        log.warning("Missing binary file: %s", rel_path)
        return _missing_response()
    return _make_binary_response(data, mtime)


@app.before_request
def _log_request() -> None:
    log.debug("%s %s", request.method, request.full_path)


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
    path = request.args.get("PATH", "1")
    rel_path = "fetchBandConditions_long.txt" if path == "2" else "fetchBandConditions.txt"
    return _serve_text_file(rel_path)


@app.get("/fetchIPGeoloc.pl")
def fetch_ip_geoloc() -> Response:
    text, mtime = read_text_and_mtime(app.config["DATA_ROOT"], "fetchIPGeoloc.txt", encoding="utf-8")
    if text is None:
        log.warning("Missing text file: fetchIPGeoloc.txt")
        return _missing_response()

    ip = request.args.get("IP") or request.remote_addr or "0.0.0.0"
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
    rel_path = "wx_de.txt" if is_de == "1" else "wx_dx.txt"
    return _serve_text_file(rel_path)


@app.get("/fetchPSKReporter.pl")
def fetch_pskreporter() -> Response:
    if any(key.startswith("of") for key in request.args.keys()):
        return _serve_text_file("fetchPSKReporter_ofgrid.txt")
    return _serve_text_file("fetchPSKReporter_bygrid.txt")


@app.get("/fetchWSPR.pl")
def fetch_wspr() -> Response:
    return _serve_text_file("fetchWSPR_bygrid.txt")


@app.get("/fetchRBN.pl")
def fetch_rbn() -> Response:
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

def init_scheduler() -> None:
    if app.config["ENABLE_SCHEDULER"]:
        start_scheduler(app)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="HamClock backend server")
    parser.add_argument("--data-root", help="Path to data root directory")
    parser.add_argument("--port", type=int, help="Port to bind (default: 8080)")
    parser.add_argument("--enable-scheduler", action="store_true", help="Enable APScheduler")
    parser.add_argument("--log-level", help="Logging level (default: INFO)")
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
    if args.strict_missing:
        app.config["STRICT_MISSING"] = True

    logging.basicConfig(level=app.config["LOG_LEVEL"])
    init_scheduler()
    app.run(host="0.0.0.0", port=app.config["PORT"])
