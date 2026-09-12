"""Shared fixtures for integration tests."""
from __future__ import annotations

import http.server
import threading
from pathlib import Path

import pytest

FIXTURES_DIR = Path(__file__).parent / "fixtures"


class _FixtureHandler(http.server.BaseHTTPRequestHandler):
    """Serves HTML files from tests/integration/fixtures/ by path."""

    def do_GET(self) -> None:
        path = self.path.split("?")[0].lstrip("/")
        if not path:
            path = "index.html"
        fixture_path = FIXTURES_DIR / path
        if not fixture_path.exists() or not fixture_path.is_file():
            self.send_response(404)
            self.send_header("Content-Type", "text/plain")
            self.end_headers()
            self.wfile.write(f"404 not found: {path}".encode())
            return
        try:
            content = fixture_path.read_bytes()
        except OSError:
            self.send_response(500)
            self.end_headers()
            return
        if path.endswith(".html") or path.endswith(".htm"):
            ctype = "text/html; charset=utf-8"
        else:
            ctype = "application/octet-stream"
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)

    def log_message(self, format: str, *args) -> None:
        # Suppress default access log
        pass


class _FixtureServer:
    """In-process HTTP server serving files from FIXTURES_DIR."""

    def __init__(self) -> None:
        self._server: http.server.HTTPServer | None = None
        self._thread: threading.Thread | None = None
        self.port: int = 0

    def start(self) -> None:
        self._server = http.server.HTTPServer(("127.0.0.1", 0), _FixtureHandler)
        self.port = self._server.server_address[1]
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        if self._server:
            self._server.shutdown()
            self._server.server_close()
        if self._thread:
            self._thread.join(timeout=5)

    @property
    def base_url(self) -> str:
        return f"http://127.0.0.1:{self.port}"


@pytest.fixture(scope="module")
def fixture_server():
    """Start the fixture server for the duration of the test module."""
    server = _FixtureServer()
    server.start()
    yield server
    server.stop()


@pytest.fixture(scope="session")
def fixtures_dir() -> Path:
    """Path to the fixtures directory."""
    return FIXTURES_DIR
