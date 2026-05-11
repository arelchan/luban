"""Span data model, inspired by OpenTelemetry."""

from __future__ import annotations

import time
import uuid
from typing import Any

from pydantic import BaseModel, Field


def _gen_id() -> str:
    return uuid.uuid4().hex[:16]


class Span(BaseModel):
    """A single trace span representing one operation (LLM call, tool call, turn, etc.)."""

    span_id: str = Field(default_factory=_gen_id)
    trace_id: str = ""
    session_id: str = ""
    parent_span_id: str | None = None
    span_type: str = ""  # "turn", "llm", "tool", ...extensible
    start_time: float = Field(default_factory=time.time)
    end_time: float | None = None
    status: str = "ok"  # "ok" | "error"
    attributes: dict[str, Any] = Field(default_factory=dict)
    input: Any = None
    output: Any = None

    def duration_ms(self) -> float | None:
        """Return span duration in milliseconds, or None if not ended."""
        if self.end_time is None:
            return None
        return (self.end_time - self.start_time) * 1000

    def to_dict(self) -> dict[str, Any]:
        """Serialize to JSON-safe dict."""
        return {
            "span_id": self.span_id,
            "trace_id": self.trace_id,
            "session_id": self.session_id,
            "parent_span_id": self.parent_span_id,
            "span_type": self.span_type,
            "start_time": self.start_time,
            "end_time": self.end_time,
            "duration_ms": self.duration_ms(),
            "status": self.status,
            "attributes": self.attributes,
            "input": _safe_serialize(self.input),
            "output": _safe_serialize(self.output),
        }


def _safe_serialize(obj: Any) -> Any:
    """Recursively convert to JSON-safe types."""
    if obj is None:
        return None
    if isinstance(obj, (str, int, float, bool)):
        return obj
    if isinstance(obj, dict):
        return {str(k): _safe_serialize(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_safe_serialize(item) for item in obj]
    # Pydantic models
    if hasattr(obj, "model_dump"):
        return _safe_serialize(obj.model_dump())
    # Dataclasses
    if hasattr(obj, "__dataclass_fields__"):
        import dataclasses
        return _safe_serialize(dataclasses.asdict(obj))
    # Fallback
    return str(obj)
