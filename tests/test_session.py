"""Tests for agentkit.session — SessionStore."""

from __future__ import annotations

import tempfile
from pathlib import Path

from agentkit.model.types import Message, ToolCall
from agentkit.session.store import SessionStore, _dict_to_message, _message_to_dict


class TestMessageSerialization:
    def test_round_trip_user_message(self):
        msg = Message(role="user", content="hello")
        d = _message_to_dict(msg)
        restored = _dict_to_message(d)
        assert restored.role == "user"
        assert restored.content == "hello"

    def test_round_trip_assistant_with_tool_calls(self):
        tc = ToolCall(id="tc1", name="calc", arguments={"expression": "2+2"})
        msg = Message(role="assistant", content="Let me calc.", tool_calls=[tc])
        d = _message_to_dict(msg)
        restored = _dict_to_message(d)
        assert restored.role == "assistant"
        assert restored.content == "Let me calc."
        assert len(restored.tool_calls) == 1
        assert restored.tool_calls[0].id == "tc1"
        assert restored.tool_calls[0].name == "calc"
        assert restored.tool_calls[0].arguments == {"expression": "2+2"}

    def test_round_trip_tool_message(self):
        msg = Message(role="tool", content="4", tool_call_id="tc1", name="calc")
        d = _message_to_dict(msg)
        restored = _dict_to_message(d)
        assert restored.role == "tool"
        assert restored.content == "4"
        assert restored.tool_call_id == "tc1"
        assert restored.name == "calc"


class TestSessionStore:
    def _make_store(self) -> tuple[Path, SessionStore]:
        td = tempfile.mkdtemp()
        store = SessionStore(sessions_dir=Path(td))
        return Path(td), store

    def test_list_sessions_empty(self):
        _, store = self._make_store()
        assert store.list_sessions() == []

    def test_create_session(self):
        _, store = self._make_store()
        meta = store.create_session(model="anthropic/claude")
        assert len(meta.id) == 8
        assert meta.model == "anthropic/claude"
        assert meta.turn_count == 0

    def test_create_and_list(self):
        _, store = self._make_store()
        store.create_session(model="m1")
        store.create_session(model="m2")
        sessions = store.list_sessions()
        assert len(sessions) == 2

    def test_save_and_load_messages(self):
        _, store = self._make_store()
        meta = store.create_session()
        messages = [
            Message(role="user", content="hello"),
            Message(role="assistant", content="hi there"),
        ]
        store.save_messages(meta.id, messages)
        loaded = store.load_session(meta.id)
        assert len(loaded) == 2
        assert loaded[0].role == "user"
        assert loaded[0].content == "hello"
        assert loaded[1].role == "assistant"

    def test_update_meta(self):
        _, store = self._make_store()
        meta = store.create_session()
        store.update_meta(meta.id, title="Test Session", turn_count=5)
        sessions = store.list_sessions()
        updated = next(s for s in sessions if s.id == meta.id)
        assert updated.title == "Test Session"
        assert updated.turn_count == 5

    def test_delete_session(self):
        td, store = self._make_store()
        meta = store.create_session()
        session_file = td / f"sess_{meta.id}.json"
        assert session_file.exists()

        store.delete_session(meta.id)
        assert not session_file.exists()
        assert store.list_sessions() == []

    def test_load_nonexistent_session(self):
        _, store = self._make_store()
        msgs = store.load_session("nonexistent")
        assert msgs == []

    def test_sessions_sorted_by_updated_at(self):
        _, store = self._make_store()
        s1 = store.create_session()
        store.update_meta(s1.id, updated_at="2026-01-01T00:00:00+00:00")
        s2 = store.create_session()
        store.update_meta(s2.id, updated_at="2026-06-01T00:00:00+00:00")

        sessions = store.list_sessions()
        # Most recent first
        assert sessions[0].id == s2.id
        assert sessions[1].id == s1.id
