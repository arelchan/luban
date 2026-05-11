"""Local HTTP server for the tracing dashboard."""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import TYPE_CHECKING

from agentkit.dashboard.template import DASHBOARD_HTML

if TYPE_CHECKING:
    from agentkit.tracing.collector import SessionTracer


class DashboardServer:
    """Serves the tracing dashboard on a local port (background thread)."""

    def __init__(self, tracer: SessionTracer):
        self._tracer = tracer
        self._server: HTTPServer | None = None
        self._thread: threading.Thread | None = None
        self._port: int = 0

    @property
    def is_running(self) -> bool:
        return self._server is not None

    @property
    def port(self) -> int:
        return self._port

    def start(self, port: int = 0) -> int:
        """Start the server on the given port (0 = auto-assign). Returns actual port."""
        if self._server is not None:
            return self._port

        tracer = self._tracer

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                if self.path == "/":
                    self.send_response(200)
                    self.send_header("Content-Type", "text/html; charset=utf-8")
                    self.end_headers()
                    self.wfile.write(DASHBOARD_HTML.encode("utf-8"))
                elif self.path == "/api/spans":
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json; charset=utf-8")
                    self.send_header("Access-Control-Allow-Origin", "*")
                    self.end_headers()
                    data = {
                        "session_id": tracer.session_id,
                        "turns": tracer.get_turns(),
                    }
                    self.wfile.write(json.dumps(data, ensure_ascii=False).encode("utf-8"))
                else:
                    self.send_response(404)
                    self.end_headers()

            def log_message(self, format, *args):
                # Suppress request logs
                pass

        self._server = HTTPServer(("127.0.0.1", port), Handler)
        self._port = self._server.server_address[1]

        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()

        return self._port

    def stop(self) -> None:
        """Shut down the server."""
        if self._server:
            self._server.shutdown()
            self._server = None
            self._thread = None
