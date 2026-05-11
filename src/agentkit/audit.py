"""Audit logging for Luban framework.

Writes structured JSONL events to ~/.agentkit/audit.log.<date> for developer
troubleshooting and root-cause analysis. Completely separate from the Tracing
system (which is conversation-level, for analyzing dialogue quality).

Usage:
    from agentkit.audit import audit
    audit("plugin.loader", "plugin.load", data={"plugin_id": "friday-tracing"})
    audit("agent.loop", "tool.call", data={"name": "read_file"}, duration_ms=120)
    audit("agent.loop", "llm.error", status="error", error="timeout after 30s")

Output format (one JSON per line):
    {"ts": "2026-05-08T09:16:43.123Z", "level": "INFO", "component": "agent.loop",
     "action": "tool.call", "status": "ok", "data": {...}, "duration_ms": 120}

Log rotation: daily, retaining audit_retention_days files (configured via DataConfig).
"""

from __future__ import annotations

import json
import logging
import logging.handlers
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_AUDIT_LOG_PATH = Path("~/.agentkit/audit.log").expanduser()
_logger: logging.Logger | None = None


def _get_logger() -> logging.Logger:
    global _logger
    if _logger is not None:
        return _logger

    logger = logging.getLogger("luban.audit")
    logger.setLevel(logging.DEBUG)
    logger.propagate = False  # never write to stderr

    if not logger.handlers:
        _AUDIT_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        # Daily rotation, keep 30 files by default (reconfigured by setup())
        handler = logging.handlers.TimedRotatingFileHandler(
            str(_AUDIT_LOG_PATH),
            when="midnight",
            backupCount=30,
            encoding="utf-8",
            utc=True,
        )
        handler.setFormatter(logging.Formatter("%(message)s"))
        logger.addHandler(handler)

    _logger = logger
    return logger


def setup(retention_days: int) -> None:
    """Configure audit log retention. Call once at startup with DataConfig value."""
    logger = _get_logger()
    for handler in logger.handlers:
        if isinstance(handler, logging.handlers.TimedRotatingFileHandler):
            handler.backupCount = max(1, retention_days) if retention_days > 0 else 36500
            break


def audit(
    component: str,
    action: str,
    status: str = "ok",
    data: dict[str, Any] | None = None,
    duration_ms: float | None = None,
    error: str | None = None,
) -> None:
    """Write one audit event.

    Args:
        component: Source component, e.g. "agent.loop", "plugin.loader"
        action:    What happened, e.g. "tool.call", "llm.error", "startup"
        status:    "ok" | "error" | "warn"
        data:      Arbitrary key-value context (serialized to JSON)
        duration_ms: How long the operation took
        error:     Error message if status == "error"
    """
    event: dict[str, Any] = {
        "ts": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z",
        "level": "ERROR" if status == "error" else ("WARN" if status == "warn" else "INFO"),
        "component": component,
        "action": action,
        "status": status,
    }
    if data:
        event["data"] = data
    if duration_ms is not None:
        event["duration_ms"] = round(duration_ms, 1)
    if error:
        event["error"] = error

    try:
        _get_logger().info(json.dumps(event, ensure_ascii=False))
    except Exception:
        pass  # audit must never crash the main flow
