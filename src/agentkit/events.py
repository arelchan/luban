"""System event injection — emit events into conversation context.

System events are injected as role=user messages with [SYSTEM timestamp] prefix,
so the model is aware of runtime environment changes (model switch, compression,
plugin errors, etc.) and can make better-informed decisions.
"""

from __future__ import annotations

from datetime import datetime

from agentkit.model.types import Message


def emit_system_event(msg: str) -> None:
    """Inject a [SYSTEM] event message into the conversation log.

    Safe to call at any time — silently no-ops if memory_manager is not yet
    available (e.g. during startup before set_runtime_context).
    """
    from agentkit.tools.builtin.context import _runtime_context

    mm = _runtime_context.get("memory_manager")
    if not mm:
        return
    ts = datetime.now().strftime("%Y-%m-%d %H:%M")
    mm.short_term.add_message(Message(role="user", content=f"[SYSTEM {ts}] {msg}"))
