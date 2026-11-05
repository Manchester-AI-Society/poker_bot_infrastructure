"""A tiny static file server for previewing or showing the exported site.

It exists for three reasons the standard ``python -m http.server`` does not
cover:

* it sends ``Cache-Control: no-store`` so a page that polls the data files
  always sees the latest export;
* it pins MIME types, because on Windows Python reads them from the
  registry, which often maps ``.js`` to ``text/plain`` and browsers refuse to
  run an ES module served that way;
* it copes with a page load. A page opens a dozen or more connections at
  once, but the standard server listens with a backlog of 5. On Windows the
  overflow is dropped and retried with exponential back-off: measured here,
  60 simultaneous requests took 19 seconds and some were refused or cut
  short. A deep backlog and keep-alive connections fix that.
"""

from __future__ import annotations

import functools
import socket
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Optional

MIME_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".mjs": "text/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".ico": "image/x-icon",
    ".txt": "text/plain; charset=utf-8",
}


class SiteServer(ThreadingHTTPServer):
    request_queue_size = 256  # the default of 5 drops a page load's burst
    daemon_threads = True


class SiteHandler(SimpleHTTPRequestHandler):
    extensions_map = {**SimpleHTTPRequestHandler.extensions_map, **MIME_TYPES}
    # Keep-alive: a page load reuses a few connections instead of opening
    # one per file. Idle connections are closed after `timeout` seconds.
    protocol_version = "HTTP/1.1"
    timeout = 30

    def end_headers(self) -> None:
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def log_message(self, format: str, *args) -> None:  # noqa: A002
        return None  # keep the organiser's terminal readable


def make_server(
    directory: Path | str, host: str = "127.0.0.1", port: int = 8000
) -> ThreadingHTTPServer:
    """Builds (does not start) a server for ``directory``."""
    handler = functools.partial(SiteHandler, directory=str(directory))
    return SiteServer((host, port), handler)


def lan_address() -> Optional[str]:
    """This machine's address on the local network, if it has one.

    Connecting a UDP socket sends nothing; it only makes the OS pick the
    interface it would use to reach the network.
    """
    probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        probe.connect(("10.255.255.255", 1))
        return probe.getsockname()[0]
    except OSError:
        return None
    finally:
        probe.close()
