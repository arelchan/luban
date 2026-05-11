"""Session store — persists conversations to disk."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from agentkit.model.types import Message, ToolCall
from agentkit.session.models import SessionData, SessionMeta

DEFAULT_SESSIONS_DIR = Path("~/.agentkit/sessions").expanduser()


class SessionStore:
    """Manages session persistence: index + per-session JSON files."""

    def __init__(self, sessions_dir: Path | None = None):
        self._dir = sessions_dir or DEFAULT_SESSIONS_DIR
        self._dir.mkdir(parents=True, exist_ok=True)
        self._index_path = self._dir / "index.json"

    def list_sessions(self) -> list[SessionMeta]:
        """List all sessions, sorted by updated_at descending (most recent first)."""
        if not self._index_path.exists():
            return []
        try:
            data = json.loads(self._index_path.read_text(encoding="utf-8"))
            sessions = [SessionMeta.model_validate(item) for item in data]
            sessions.sort(key=lambda s: s.updated_at, reverse=True)
            return sessions
        except (json.JSONDecodeError, Exception):
            return []

    def create_session(self, model: str = "") -> SessionMeta:
        """Create a new empty session."""
        session_id = uuid.uuid4().hex[:8]
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        meta = SessionMeta(
            id=session_id,
            title="",
            created_at=now,
            updated_at=now,
            turn_count=0,
            model=model,
        )
        # Create empty session file
        session_data = SessionData(id=session_id, messages=[])
        self._write_session_file(session_id, session_data)
        # Add to index
        self._add_to_index(meta)
        return meta

    def load_session(self, session_id: str) -> list[Message]:
        """Load a session's messages from disk."""
        path = self._dir / f"sess_{session_id}.json"
        if not path.exists():
            return []
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            session_data = SessionData.model_validate(data)
            return [_dict_to_message(m) for m in session_data.messages]
        except (json.JSONDecodeError, Exception):
            return []

    def save_messages(self, session_id: str, messages: list[Message]) -> None:
        """Save the full message list for a session."""
        serialized = [_message_to_dict(m) for m in messages]
        session_data = SessionData(id=session_id, messages=serialized)
        self._write_session_file(session_id, session_data)

    def update_meta(self, session_id: str, **kwargs: Any) -> None:
        """Update session metadata in the index."""
        sessions = self.list_sessions()
        for s in sessions:
            if s.id == session_id:
                for key, value in kwargs.items():
                    if hasattr(s, key):
                        setattr(s, key, value)
                break
        self._write_index(sessions)

    def delete_session(self, session_id: str) -> None:
        """Delete a session (file + trace dir + index entry)."""
        import shutil
        # Remove session file
        path = self._dir / f"sess_{session_id}.json"
        if path.exists():
            path.unlink()
        # Remove trace directory
        trace_dir = self._dir / "traces" / session_id
        if trace_dir.exists():
            shutil.rmtree(trace_dir)
        # Remove from index
        sessions = [s for s in self.list_sessions() if s.id != session_id]
        self._write_index(sessions)

    # ─── Private helpers ───

    def _write_session_file(self, session_id: str, data: SessionData) -> None:
        path = self._dir / f"sess_{session_id}.json"
        path.write_text(
            json.dumps(data.model_dump(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def _add_to_index(self, meta: SessionMeta) -> None:
        sessions = self.list_sessions()
        sessions.append(meta)
        self._write_index(sessions)

    def _write_index(self, sessions: list[SessionMeta]) -> None:
        data = [s.model_dump() for s in sessions]
        self._index_path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )


# ─── Message serialization ───


def _message_to_dict(msg: Message) -> dict:
    """Serialize a Message to a JSON-safe dict."""
    d: dict[str, Any] = {"role": msg.role, "content": msg.content}
    if msg.tool_calls:
        d["tool_calls"] = [
            {"id": tc.id, "name": tc.name, "arguments": tc.arguments}
            for tc in msg.tool_calls
        ]
    if msg.tool_call_id:
        d["tool_call_id"] = msg.tool_call_id
    if msg.name:
        d["name"] = msg.name
    return d


def _dict_to_message(d: dict) -> Message:
    """Deserialize a dict back to a Message."""
    tool_calls = []
    if "tool_calls" in d and d["tool_calls"]:
        for tc_data in d["tool_calls"]:
            tool_calls.append(ToolCall(
                id=tc_data["id"],
                name=tc_data["name"],
                arguments=tc_data.get("arguments", {}),
            ))
    return Message(
        role=d["role"],
        content=d.get("content"),
        tool_calls=tool_calls,
        tool_call_id=d.get("tool_call_id"),
        name=d.get("name"),
    )
