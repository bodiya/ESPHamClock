#!/usr/bin/env python3
from __future__ import annotations

import argparse
import logging
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Dict
from urllib.parse import urljoin

import requests


log = logging.getLogger("hamclock-client-redirect")


def _filtered_headers(headers: Dict[str, str]) -> Dict[str, str]:
    filtered = {}
    for key, value in headers.items():
        lk = key.lower()
        if lk in ("host", "connection", "content-length"):
            continue
        filtered[key] = value
    return filtered


class RedirectProxyHandler(BaseHTTPRequestHandler):
    server_version = "HamClockRedirectProxy/0.1"

    def do_GET(self) -> None:  # noqa: N802
        backend_base = self.server.backend_base
        url = urljoin(backend_base, self.path)
        session = self.server.session

        headers = _filtered_headers({k: v for k, v in self.headers.items()})
        try:
            resp = session.get(url, headers=headers, timeout=self.server.timeout, allow_redirects=True)
        except requests.TooManyRedirects:
            self.send_error(502, "Too many redirects")
            return
        except requests.RequestException as exc:
            log.warning("Proxy error: %s", exc)
            self.send_error(502, "Proxy error")
            return

        self.send_response(resp.status_code)
        for key, value in resp.headers.items():
            lk = key.lower()
            if lk in ("transfer-encoding", "connection", "content-length"):
                continue
            self.send_header(key, value)
        self.send_header("Content-Length", str(len(resp.content)))
        self.end_headers()
        if resp.content:
            self.wfile.write(resp.content)

    def log_message(self, format: str, *args) -> None:
        log.info("%s - %s", self.address_string(), format % args)


def main() -> None:
    parser = argparse.ArgumentParser(description="HamClock client-side redirect proxy")
    parser.add_argument("--listen-host", default="0.0.0.0")
    parser.add_argument("--listen-port", type=int, default=8088)
    parser.add_argument("--backend", required=True, help="Backend base URL, e.g. http://127.0.0.1:8123")
    parser.add_argument("--timeout", type=float, default=15.0)
    parser.add_argument("--max-redirects", type=int, default=3)
    parser.add_argument("--log-level", default="INFO")
    args = parser.parse_args()

    logging.basicConfig(level=args.log_level.upper())

    session = requests.Session()
    session.max_redirects = args.max_redirects

    server = HTTPServer((args.listen_host, args.listen_port), RedirectProxyHandler)
    server.backend_base = args.backend.rstrip("/") + "/"
    server.timeout = args.timeout
    server.session = session

    log.info("Redirect proxy listening on %s:%d", args.listen_host, args.listen_port)
    log.info("Forwarding to %s", server.backend_base)
    server.serve_forever()


if __name__ == "__main__":
    main()
