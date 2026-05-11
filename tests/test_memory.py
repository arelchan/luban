"""Tests for agentkit.memory — ShortTermMemory, MemoryManager."""

from __future__ import annotations

import pytest

from agentkit.config.models import LongTermMemoryConfig, MemoryConfig
from agentkit.memory.short_term import ShortTermMemory, estimate_tokens
from agentkit.model.types import Message


# ─── ShortTermMemory ───


class TestShortTermMemory:
    def _make_memory(self, max_tokens: int = 100000) -> tuple[MemoryConfig, ShortTermMemory]:
        config = MemoryConfig(short_term_max_tokens=max_tokens)
        return config, ShortTermMemory(config)

    def test_add_and_get_messages(self):
        _, mem = self._make_memory()
        mem.add_message(Message(role="user", content="hello"))
        mem.add_message(Message(role="assistant", content="hi"))
        msgs = mem.get_messages_for_llm()
        assert len(msgs) == 2
        assert msgs[0].role == "user"
        assert msgs[1].role == "assistant"

    def test_add_messages_bulk(self):
        _, mem = self._make_memory()
        mem.add_messages([
            Message(role="user", content="a"),
            Message(role="assistant", content="b"),
        ])
        assert len(mem.full_log) == 2

    def test_turn_count(self):
        _, mem = self._make_memory()
        assert mem.turn_count == 0
        mem.add_message(Message(role="user", content="q1"))
        mem.add_message(Message(role="assistant", content="a1"))
        mem.add_message(Message(role="user", content="q2"))
        assert mem.turn_count == 2

    def test_no_message_limit_only_token_budget(self):
        """Messages are never truncated by count — only token budget matters."""
        _, mem = self._make_memory(max_tokens=100000)
        for i in range(100):
            mem.add_message(Message(role="user", content=f"msg{i}"))
        # All 100 messages should be in context (small content, within budget)
        msgs = mem.get_messages_for_llm()
        assert len(msgs) == 100

    def test_context_tokens_estimation(self):
        _, mem = self._make_memory()
        mem.add_message(Message(role="user", content="a" * 200))  # 200 chars → ~100 tokens
        assert mem.context_tokens == 100

    def test_needs_compression(self):
        # Budget = 50 tokens → 100 chars of content should trigger
        _, mem = self._make_memory(max_tokens=50)
        mem.add_message(Message(role="user", content="a" * 200))  # 200 chars → 100 tokens > 50
        assert mem.needs_compression is True

    def test_no_compression_within_budget(self):
        _, mem = self._make_memory(max_tokens=1000)
        mem.add_message(Message(role="user", content="hello"))
        assert mem.needs_compression is False

    def test_compress(self):
        _, mem = self._make_memory(max_tokens=50)
        # Add 10 messages
        for i in range(10):
            mem.add_message(Message(role="user", content=f"message number {i}"))

        # Compress, keeping recent 3
        mem.compress("This is a summary of the conversation.", keep_recent=3)

        # Only 3 recent messages remain in log
        assert len(mem.full_log) == 3
        assert mem.full_log[0].content == "message number 7"

        # LLM view includes summary
        msgs = mem.get_messages_for_llm()
        assert msgs[0].role == "system"
        assert "Context Summary" in msgs[0].content
        assert "This is a summary" in msgs[0].content
        assert len(msgs) == 4  # summary + 3 recent

    def test_compress_accumulates_summaries(self):
        _, mem = self._make_memory(max_tokens=50)
        for i in range(10):
            mem.add_message(Message(role="user", content=f"msg{i}"))

        mem.compress("First summary.", keep_recent=4)
        # Add more and compress again
        for i in range(10, 20):
            mem.add_message(Message(role="user", content=f"msg{i}"))
        mem.compress("Second summary.", keep_recent=4)

        msgs = mem.get_messages_for_llm()
        # Summary should contain both
        assert "First summary" in msgs[0].content
        assert "Second summary" in msgs[0].content

    def test_compress_skips_if_too_few_messages(self):
        _, mem = self._make_memory()
        for i in range(3):
            mem.add_message(Message(role="user", content=f"msg{i}"))
        mem.compress("summary", keep_recent=6)
        # Not compressed — still 3 messages
        assert len(mem.full_log) == 3

    def test_system_messages_always_included(self):
        _, mem = self._make_memory()
        mem.set_system_messages([Message(role="system", content="You are helpful.")])
        mem.add_message(Message(role="user", content="hi"))

        msgs = mem.get_messages_for_llm()
        assert msgs[0].role == "system"
        assert msgs[0].content == "You are helpful."
        assert msgs[1].content == "hi"

    def test_clear_keeps_system(self):
        _, mem = self._make_memory()
        mem.set_system_messages([Message(role="system", content="sys")])
        mem.add_message(Message(role="user", content="hello"))
        mem.clear()

        assert mem.turn_count == 0
        assert len(mem.full_log) == 0
        msgs = mem.get_messages_for_llm()
        assert len(msgs) == 1
        assert msgs[0].role == "system"

    def test_get_recent_log(self):
        _, mem = self._make_memory()
        for i in range(5):
            mem.add_message(Message(role="user", content=f"msg{i}"))

        recent = mem.get_recent_log(3)
        assert len(recent) == 3
        assert recent[0].content == "msg2"

        all_log = mem.get_recent_log(None)
        assert len(all_log) == 5

    def test_set_system_messages(self):
        _, mem = self._make_memory()
        mem.set_system_messages([
            Message(role="system", content="persona"),
            Message(role="system", content="instructions"),
        ])
        sys_msgs = mem.get_system_messages()
        assert len(sys_msgs) == 2
        assert sys_msgs[0].content == "persona"


# ─── estimate_tokens ───


class TestEstimateTokens:
    def test_empty(self):
        assert estimate_tokens([]) == 0

    def test_simple_text(self):
        msgs = [Message(role="user", content="a" * 100)]
        assert estimate_tokens(msgs) == 50  # 100 chars / 2

    def test_with_tool_calls(self):
        from agentkit.model.types import ToolCall
        msgs = [Message(role="assistant", content="ok", tool_calls=[
            ToolCall(id="1", name="read_file", arguments={"path": "/tmp/x"})
        ])]
        # content(2) + tool name(9) + args str len
        tokens = estimate_tokens(msgs)
        assert tokens > 0


# ─── MemoryManager ───


class TestMemoryManager:
    def test_init_with_long_term_disabled(self):
        from agentkit.memory.manager import MemoryManager

        config = MemoryConfig(
            long_term=LongTermMemoryConfig(enabled=False),
        )
        assert config.long_term.enabled is False

    def test_add_and_get_messages(self):
        from unittest.mock import MagicMock

        from agentkit.memory.manager import MemoryManager

        config = MemoryConfig(long_term=LongTermMemoryConfig(enabled=False))
        mock_client = MagicMock()
        manager = MemoryManager(config, mock_client)

        manager.add_message(Message(role="user", content="hello"))
        manager.add_message(Message(role="assistant", content="hi"))

        msgs = manager.get_messages_for_llm()
        assert len(msgs) == 2

    def test_clear(self):
        from unittest.mock import MagicMock

        from agentkit.memory.manager import MemoryManager

        config = MemoryConfig(long_term=LongTermMemoryConfig(enabled=False))
        mock_client = MagicMock()
        manager = MemoryManager(config, mock_client)

        manager.add_message(Message(role="user", content="hello"))
        manager.clear()
        assert manager.get_messages_for_llm() == []

    @pytest.mark.asyncio
    async def test_on_turn_complete_no_extraction_when_disabled(self):
        from unittest.mock import MagicMock

        from agentkit.memory.manager import MemoryManager

        config = MemoryConfig(long_term=LongTermMemoryConfig(enabled=False))
        mock_client = MagicMock()
        manager = MemoryManager(config, mock_client)

        # Should not raise even without long-term memory
        await manager.on_turn_complete()

    @pytest.mark.asyncio
    async def test_extract_returns_none_when_disabled(self):
        from unittest.mock import MagicMock

        from agentkit.memory.manager import MemoryManager

        config = MemoryConfig(long_term=LongTermMemoryConfig(enabled=False))
        mock_client = MagicMock()
        manager = MemoryManager(config, mock_client)

        result = await manager.extract()
        assert result is None

    @pytest.mark.asyncio
    async def test_on_session_end_no_crash(self):
        from unittest.mock import MagicMock

        from agentkit.memory.manager import MemoryManager

        config = MemoryConfig(long_term=LongTermMemoryConfig(enabled=False))
        mock_client = MagicMock()
        manager = MemoryManager(config, mock_client)

        await manager.on_session_end()  # Should not raise

    @pytest.mark.asyncio
    async def test_compress_if_needed_triggers(self):
        from unittest.mock import AsyncMock, MagicMock

        from agentkit.memory.manager import MemoryManager

        # Very small token budget to force compression
        config = MemoryConfig(
            short_term_max_tokens=50,
            long_term=LongTermMemoryConfig(enabled=False),
        )
        mock_client = MagicMock()
        # Mock complete() to return a summary
        mock_resp = MagicMock()
        mock_resp.content = "Summary of older messages"
        mock_client.complete = AsyncMock(return_value=mock_resp)

        compress_called = []
        manager = MemoryManager(
            config, mock_client,
            on_compress=lambda before, after: compress_called.append((before, after)),
        )

        # Add enough messages to exceed budget (each ~50 chars = 25 tokens)
        # Need user messages interspersed so last turn detection works
        for i in range(10):
            manager.add_message(Message(role="user", content=f"This is message number {i} with some content"))
            manager.add_message(Message(role="assistant", content=f"Response to message {i}"))

        result = await manager.compress_if_needed()
        assert result is True
        # Callback was invoked
        assert len(compress_called) == 1
        before_tokens, after_tokens = compress_called[0]
        assert before_tokens > after_tokens

    @pytest.mark.asyncio
    async def test_compress_if_needed_skips_when_within_budget(self):
        from unittest.mock import MagicMock

        from agentkit.memory.manager import MemoryManager

        config = MemoryConfig(
            short_term_max_tokens=100000,
            long_term=LongTermMemoryConfig(enabled=False),
        )
        mock_client = MagicMock()
        manager = MemoryManager(config, mock_client)

        manager.add_message(Message(role="user", content="short"))
        result = await manager.compress_if_needed()
        assert result is False


# ─── Phase 1 Trimming ───


class TestTrimForCompression:
    def _make_memory(self, max_tokens: int = 100000) -> tuple[MemoryConfig, ShortTermMemory]:
        config = MemoryConfig(short_term_max_tokens=max_tokens)
        return config, ShortTermMemory(config)

    def test_trims_long_tool_results(self):
        _, mem = self._make_memory()
        # Add a user message, then assistant+tool calls, then another user (last turn)
        mem.add_message(Message(role="user", content="read the file"))
        mem.add_message(Message(role="assistant", content="", tool_calls=[]))
        mem.add_message(Message(role="tool", content="x" * 1000, name="read_file", tool_call_id="t1"))
        mem.add_message(Message(role="assistant", content="Here's what I found"))
        # Last turn (should not be trimmed)
        mem.add_message(Message(role="user", content="thanks"))

        freed = mem.trim_for_compression()
        assert freed > 0
        # Tool result should be truncated
        tool_msg = mem.full_log[2]
        assert len(tool_msg.content) < 300
        assert "read_file" in tool_msg.content
        assert "1000字" in tool_msg.content

    def test_does_not_trim_last_turn(self):
        _, mem = self._make_memory()
        mem.add_message(Message(role="user", content="old question"))
        mem.add_message(Message(role="assistant", content="old answer"))
        # Last turn with long tool result
        mem.add_message(Message(role="user", content="new question"))
        mem.add_message(Message(role="tool", content="y" * 1000, name="shell", tool_call_id="t2"))

        mem.trim_for_compression()
        # Last turn's tool result should be untouched
        last_tool = mem.full_log[3]
        assert len(last_tool.content) == 1000

    def test_trims_long_assistant_messages(self):
        _, mem = self._make_memory()
        mem.add_message(Message(role="user", content="explain something"))
        mem.add_message(Message(role="assistant", content="A" * 800))
        mem.add_message(Message(role="user", content="next question"))

        mem.trim_for_compression()
        assistant_msg = mem.full_log[1]
        assert len(assistant_msg.content) < 400
        assert "+500字" in assistant_msg.content  # 800 - 300 = 500


# ─── ContextWindowExceeded ───


class TestContextWindowExceeded:
    def test_exception_importable(self):
        from agentkit.model.client import ContextWindowExceeded
        exc = ContextWindowExceeded("too long")
        assert str(exc) == "too long"


# ─── Compression Force Mode ───


class TestCompressionForce:
    @pytest.mark.asyncio
    async def test_force_compression_even_within_budget(self):
        from unittest.mock import AsyncMock, MagicMock

        from agentkit.memory.manager import MemoryManager

        config = MemoryConfig(
            short_term_max_tokens=100000,  # Very large budget
            long_term=LongTermMemoryConfig(enabled=False),
        )
        mock_client = MagicMock()
        mock_resp = MagicMock()
        mock_resp.content = "Compressed summary"
        mock_client.complete = AsyncMock(return_value=mock_resp)

        compress_called = []
        manager = MemoryManager(
            config, mock_client,
            on_compress=lambda before, after: compress_called.append((before, after)),
        )

        # Add messages (well within budget)
        for i in range(6):
            manager.add_message(Message(role="user", content=f"Message {i} content here"))
            manager.add_message(Message(role="assistant", content=f"Response {i}"))

        # Normal compress should skip (within budget)
        result = await manager.compress_if_needed(force=False)
        assert result is False

        # Force compress should proceed
        result = await manager.compress_if_needed(force=True)
        assert result is True
        assert len(compress_called) == 1
