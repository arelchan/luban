"""Tests for agentkit.dashboard — DashboardServer."""

from __future__ import annotations

import json
import urllib.request

import pytest

from agentkit.dashboard.server import DashboardServer
from agentkit.tracing.collector import SessionTracer


class TestDashboardServer:
    def test_initial_state(self):
        tracer = SessionTracer()
        server = DashboardServer(tracer)
        assert server.is_running is False
        assert server.port == 0

    def test_start_and_stop(self):
        tracer = SessionTracer()
        server = DashboardServer(tracer)
        try:
            port = server.start()
            assert port > 0
            assert server.is_running is True
            assert server.port == port
        finally:
            server.stop()
        assert server.is_running is False

    def test_start_idempotent(self):
        tracer = SessionTracer()
        server = DashboardServer(tracer)
        try:
            port1 = server.start()
            port2 = server.start()
            assert port1 == port2
        finally:
            server.stop()

    def test_serve_html(self):
        tracer = SessionTracer()
        server = DashboardServer(tracer)
        try:
            port = server.start()
            resp = urllib.request.urlopen(f"http://127.0.0.1:{port}/")
            html = resp.read().decode("utf-8")
            assert "<html" in html.lower()
            assert "Luban" in html
        finally:
            server.stop()

    def test_serve_api_spans_empty(self):
        tracer = SessionTracer()
        server = DashboardServer(tracer)
        try:
            port = server.start()
            resp = urllib.request.urlopen(f"http://127.0.0.1:{port}/api/spans")
            data = json.loads(resp.read().decode("utf-8"))
            assert "session_id" in data
            assert data["turns"] == []
        finally:
            server.stop()

    def test_serve_api_spans_with_data(self):
        tracer = SessionTracer()
        turn = tracer.start_turn("hello")
        llm = tracer.start_span("llm", parent=turn, input={"model": "claude"})
        tracer.end_span(llm, output={"content": "hi"})
        tracer.end_span(turn, output="hi")

        server = DashboardServer(tracer)
        try:
            port = server.start()
            resp = urllib.request.urlopen(f"http://127.0.0.1:{port}/api/spans")
            data = json.loads(resp.read().decode("utf-8"))
            assert len(data["turns"]) == 1
            assert data["turns"][0]["span"]["span_type"] == "turn"
            assert len(data["turns"][0]["children"]) == 1
        finally:
            server.stop()

    def test_404_for_unknown_path(self):
        tracer = SessionTracer()
        server = DashboardServer(tracer)
        try:
            port = server.start()
            with pytest.raises(urllib.error.HTTPError) as exc_info:
                urllib.request.urlopen(f"http://127.0.0.1:{port}/unknown")
            assert exc_info.value.code == 404
        finally:
            server.stop()

    def test_stop_idempotent(self):
        tracer = SessionTracer()
        server = DashboardServer(tracer)
        server.stop()  # Not started, should not raise
        port = server.start()
        server.stop()
        server.stop()  # Already stopped, should not raise
