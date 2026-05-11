"""Session-level span collector with per-day JSONL file persistence."""

from __future__ import annotations

import json
import time
import uuid
from datetime import date
from pathlib import Path
from typing import Any

from agentkit.tracing.models import Span

DEFAULT_SESSIONS_DIR = Path("~/.agentkit/sessions").expanduser()


class SessionTracer:
    """Collects spans for one CLI session, persisted to daily JSONL trace files.

    Storage layout::

        ~/.agentkit/sessions/traces/{session_id}/
            2026-05-10.jsonl
            2026-05-11.jsonl

    Each line in a .jsonl file is one span (JSON object).
    Spans are appended immediately when they end (or on flush).
    On reload, lines are deduplicated by span_id (last occurrence wins),
    so flush + later end_span for the same span is safe.
    Legacy .json array files are also supported on read.

    Usage:
        tracer = SessionTracer(session_id="abc123")
        turn = tracer.start_turn("hello")
        llm = tracer.start_span("llm", parent=turn, input={...})
        tracer.end_span(llm, output={...})
        tracer.end_span(turn, output="hi there")
    """

    def __init__(self, session_id: str | None = None, sessions_dir: Path | None = None):
        self.session_id = session_id or uuid.uuid4().hex[:16]
        self._base_dir = sessions_dir or DEFAULT_SESSIONS_DIR
        self._trace_dir = self._base_dir / "traces" / self.session_id
        self._trace_dir.mkdir(parents=True, exist_ok=True)
        self._spans: list[Span] = []
        self._persisted: set[str] = set()  # span_ids already written to disk
        self._turn_count = 0
        self._history_loaded = False
        # Plugin hook: called with span.to_dict() after each span ends.
        self.on_span_end: Any | None = None

    def _today_path(self) -> Path:
        return self._trace_dir / f"{date.today().isoformat()}.jsonl"

    def _append_to_file(self, span: Span) -> None:
        """Append a single span as one JSON line to today's file."""
        line = json.dumps(span.to_dict(), ensure_ascii=False)
        with open(self._today_path(), "a", encoding="utf-8") as f:
            f.write(line + "\n")
        self._persisted.add(span.span_id)

    def _ensure_history_loaded(self) -> None:
        """Load historical spans from disk on first access (lazy load)."""
        if self._history_loaded:
            return
        self._history_loaded = True
        if not self._trace_dir.exists():
            return
        # Support both .jsonl (new) and .json (legacy) files
        files = sorted(
            list(self._trace_dir.glob("*.jsonl")) + list(self._trace_dir.glob("*.json"))
        )
        seen: dict[str, Span] = {}
        for f in files:
            try:
                text = f.read_text(encoding="utf-8").strip()
                if not text:
                    continue
                if f.suffix == ".jsonl":
                    # JSONL: one span per line
                    for line in text.splitlines():
                        line = line.strip()
                        if not line:
                            continue
                        item = json.loads(line)
                        span = Span.model_validate(item)
                        seen[span.span_id] = span
                else:
                    # Legacy JSON array format
                    data = json.loads(text)
                    if isinstance(data, list):
                        for item in data:
                            span = Span.model_validate(item)
                            seen[span.span_id] = span
            except (json.JSONDecodeError, Exception):
                continue
        self._spans = list(seen.values())
        self._persisted = set(seen.keys())
        # Restore turn count
        self._turn_count = sum(1 for s in self._spans if s.span_type == "turn")

    def start_turn(self, user_input: str) -> Span:
        """Create a root turn span."""
        self._ensure_history_loaded()
        self._turn_count += 1
        span = Span(
            trace_id=uuid.uuid4().hex[:16],
            session_id=self.session_id,
            parent_span_id=None,
            span_type="turn",
            input=user_input,
            attributes={"turn_index": self._turn_count},
        )
        self._spans.append(span)
        return span

    def start_span(
        self,
        span_type: str,
        parent: Span,
        input: Any = None,
        attributes: dict[str, Any] | None = None,
    ) -> Span:
        """Create a child span under a parent."""
        self._ensure_history_loaded()
        span = Span(
            trace_id=parent.trace_id,
            session_id=self.session_id,
            parent_span_id=parent.span_id,
            span_type=span_type,
            input=input,
            attributes=attributes or {},
        )
        self._spans.append(span)
        return span

    def end_span(
        self,
        span: Span,
        output: Any = None,
        status: str = "ok",
    ) -> None:
        """Mark a span as completed and persist immediately."""
        span.end_time = time.time()
        span.output = output
        span.status = status
        self._append_to_file(span)
        # Notify plugins
        if self.on_span_end is not None:
            try:
                self.on_span_end(span.to_dict())
            except Exception:
                pass

    def flush(self) -> None:
        """Persist any spans not yet written to disk (e.g. unended spans)."""
        for span in self._spans:
            if span.span_id not in self._persisted:
                self._append_to_file(span)

    def get_all_spans(self) -> list[dict[str, Any]]:
        """Return all spans as serialized dicts."""
        self._ensure_history_loaded()
        return [s.to_dict() for s in self._spans]

    def get_turns(self) -> list[dict[str, Any]]:
        """Return spans as a recursive tree (supports subagent nesting)."""
        self._ensure_history_loaded()
        children_map: dict[str, list[Span]] = {}
        for s in self._spans:
            if s.parent_span_id:
                children_map.setdefault(s.parent_span_id, []).append(s)

        def build_node(span: Span) -> dict[str, Any]:
            kids = sorted(children_map.get(span.span_id, []), key=lambda s: s.start_time)
            return {
                "span": span.to_dict(),
                "children": [build_node(k) for k in kids],
            }

        roots = sorted(
            [s for s in self._spans if s.parent_span_id is None],
            key=lambda s: s.start_time,
        )
        return [build_node(r) for r in roots]
