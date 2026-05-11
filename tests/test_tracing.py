"""Tests for agentkit.tracing — Span model and SessionTracer."""

from __future__ import annotations

import time

from agentkit.tracing.collector import SessionTracer
from agentkit.tracing.models import Span, _safe_serialize


# ─── Span model ───


class TestSpan:
    def test_default_fields(self):
        span = Span()
        assert len(span.span_id) == 16
        assert span.trace_id == ""
        assert span.parent_span_id is None
        assert span.span_type == ""
        assert span.status == "ok"
        assert span.end_time is None
        assert span.start_time > 0

    def test_duration_ms_not_ended(self):
        span = Span()
        assert span.duration_ms() is None

    def test_duration_ms_after_end(self):
        span = Span()
        span.start_time = 1000.0
        span.end_time = 1000.5
        assert span.duration_ms() == 500.0

    def test_to_dict(self):
        span = Span(
            span_type="llm",
            trace_id="trace123",
            session_id="sess456",
            status="ok",
            input={"model": "claude"},
            output={"content": "hello"},
        )
        span.end_time = span.start_time + 0.1

        d = span.to_dict()
        assert d["span_type"] == "llm"
        assert d["trace_id"] == "trace123"
        assert d["session_id"] == "sess456"
        assert d["input"] == {"model": "claude"}
        assert d["output"] == {"content": "hello"}
        assert d["duration_ms"] is not None
        assert d["duration_ms"] == pytest.approx(100.0, abs=1.0)


# ─── _safe_serialize ───


class TestSafeSerialize:
    def test_primitives(self):
        assert _safe_serialize(None) is None
        assert _safe_serialize("hello") == "hello"
        assert _safe_serialize(42) == 42
        assert _safe_serialize(3.14) == 3.14
        assert _safe_serialize(True) is True

    def test_dict(self):
        assert _safe_serialize({"a": 1, "b": "c"}) == {"a": 1, "b": "c"}

    def test_list(self):
        assert _safe_serialize([1, "a", None]) == [1, "a", None]

    def test_nested(self):
        data = {"messages": [{"role": "user", "content": "hi"}]}
        result = _safe_serialize(data)
        assert result["messages"][0]["role"] == "user"

    def test_pydantic_model(self):
        from pydantic import BaseModel

        class Foo(BaseModel):
            x: int = 1

        result = _safe_serialize(Foo(x=5))
        assert result == {"x": 5}

    def test_dataclass(self):
        from agentkit.model.types import ToolCall

        tc = ToolCall(id="tc1", name="calc", arguments={"x": 1})
        result = _safe_serialize(tc)
        assert result["id"] == "tc1"
        assert result["name"] == "calc"

    def test_fallback_to_str(self):
        class Custom:
            def __str__(self):
                return "custom_obj"

        result = _safe_serialize(Custom())
        assert result == "custom_obj"


# ─── SessionTracer ───


class TestSessionTracer:
    def test_init(self):
        tracer = SessionTracer()
        assert len(tracer.session_id) == 16
        assert tracer._spans == []
        assert tracer._turn_count == 0

    def test_custom_session_id(self):
        tracer = SessionTracer(session_id="mysession")
        assert tracer.session_id == "mysession"

    def test_start_turn(self):
        tracer = SessionTracer()
        turn = tracer.start_turn("hello")
        assert turn.span_type == "turn"
        assert turn.input == "hello"
        assert turn.parent_span_id is None
        assert turn.session_id == tracer.session_id
        assert turn.attributes["turn_index"] == 1
        assert len(turn.trace_id) == 16

    def test_start_span_child(self):
        tracer = SessionTracer()
        turn = tracer.start_turn("hi")
        llm = tracer.start_span("llm", parent=turn, input={"model": "claude"}, attributes={"model": "claude"})
        assert llm.span_type == "llm"
        assert llm.parent_span_id == turn.span_id
        assert llm.trace_id == turn.trace_id
        assert llm.input == {"model": "claude"}

    def test_end_span(self):
        tracer = SessionTracer()
        turn = tracer.start_turn("hi")
        time.sleep(0.01)
        tracer.end_span(turn, output="bye", status="ok")
        assert turn.end_time is not None
        assert turn.output == "bye"
        assert turn.status == "ok"

    def test_end_span_error(self):
        tracer = SessionTracer()
        turn = tracer.start_turn("hi")
        tracer.end_span(turn, output={"error": "timeout"}, status="error")
        assert turn.status == "error"

    def test_get_all_spans(self):
        tracer = SessionTracer()
        turn = tracer.start_turn("hi")
        llm = tracer.start_span("llm", parent=turn, input={})
        tracer.end_span(llm, output={"content": "hello"})
        tracer.end_span(turn, output="hello")

        all_spans = tracer.get_all_spans()
        assert len(all_spans) == 2
        assert all_spans[0]["span_type"] == "turn"
        assert all_spans[1]["span_type"] == "llm"

    def test_get_turns_tree(self):
        tracer = SessionTracer()

        # Turn 1
        turn1 = tracer.start_turn("q1")
        llm1 = tracer.start_span("llm", parent=turn1, input={})
        tracer.end_span(llm1, output={"content": "a1"})
        tool1 = tracer.start_span("tool", parent=turn1, input={"name": "calc"})
        tracer.end_span(tool1, output={"result": "4"})
        tracer.end_span(turn1, output="a1")

        # Turn 2
        turn2 = tracer.start_turn("q2")
        llm2 = tracer.start_span("llm", parent=turn2, input={})
        tracer.end_span(llm2, output={"content": "a2"})
        tracer.end_span(turn2, output="a2")

        turns = tracer.get_turns()
        assert len(turns) == 2
        assert turns[0]["span"]["input"] == "q1"
        assert len(turns[0]["children"]) == 2  # llm + tool
        assert turns[1]["span"]["input"] == "q2"
        assert len(turns[1]["children"]) == 1  # llm only

    def test_turn_count_increments(self):
        tracer = SessionTracer()
        tracer.start_turn("a")
        tracer.start_turn("b")
        tracer.start_turn("c")
        assert tracer._turn_count == 3

    def test_multiple_turns_different_trace_ids(self):
        tracer = SessionTracer()
        t1 = tracer.start_turn("a")
        t2 = tracer.start_turn("b")
        assert t1.trace_id != t2.trace_id


    def test_persistence_save_and_load(self, tmp_path):
        """Trace data persists to daily file and reloads on new tracer instance."""
        from datetime import date

        # Create tracer and add spans
        tracer1 = SessionTracer(session_id="persist_test", sessions_dir=tmp_path)
        turn = tracer1.start_turn("hello")
        llm = tracer1.start_span("llm", parent=turn, input={"model": "test"})
        tracer1.end_span(llm, output={"content": "hi"})
        tracer1.end_span(turn, output="hi")

        # Verify daily trace file was written
        today = date.today().isoformat()
        trace_dir = tmp_path / "traces" / "persist_test"
        assert trace_dir.exists()
        assert (trace_dir / f"{today}.jsonl").exists()

        # Create a new tracer with same session_id — history loads lazily on first use
        tracer2 = SessionTracer(session_id="persist_test", sessions_dir=tmp_path)
        turns = tracer2.get_turns()
        assert len(turns) == 1
        assert turns[0]["span"]["input"] == "hello"
        assert turns[0]["children"][0]["span"]["span_type"] == "llm"

        # New turn should continue from loaded turn_count=1
        turn2 = tracer2.start_turn("world")
        assert tracer2._turn_count == 2
        assert turn2.attributes["turn_index"] == 2

    def test_persistence_empty_session(self, tmp_path):
        """New session with no trace file starts fresh."""
        tracer = SessionTracer(session_id="new_sess", sessions_dir=tmp_path)
        assert tracer._turn_count == 0
        assert tracer._spans == []

    def test_flush(self, tmp_path):
        """flush() persists spans even without ending a turn."""
        from datetime import date

        tracer = SessionTracer(session_id="flush_test", sessions_dir=tmp_path)
        turn = tracer.start_turn("test")
        tracer.flush()

        today = date.today().isoformat()
        trace_file = tmp_path / "traces" / "flush_test" / f"{today}.jsonl"
        assert trace_file.exists()

        # Reload — history loads lazily via get_all_spans
        tracer2 = SessionTracer(session_id="flush_test", sessions_dir=tmp_path)
        assert len(tracer2.get_all_spans()) == 1


import pytest  # noqa: E402 (for pytest.approx)
