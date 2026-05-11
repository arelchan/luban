"""Memory manager: coordinates short-term and long-term memory."""

from __future__ import annotations

from typing import TYPE_CHECKING, Callable

from agentkit.config.models import MemoryConfig
from agentkit.memory.long_term import LongTermMemory
from agentkit.memory.prompts import COMPRESSION_PROMPT
from agentkit.memory.short_term import ShortTermMemory, estimate_tokens
from agentkit.model.client import ModelClient
from agentkit.model.types import Message

if TYPE_CHECKING:
    from agentkit.tracing.collector import SessionTracer

# Threshold: if remaining context < this, trigger preventive compression
_REMAINING_THRESHOLD = 5000


class MemoryManager:
    """Coordinates short-term conversation log and long-term memory extraction.

    Short-term: the full conversation log for this session.
    Long-term: periodically extracts knowledge from the log → memory.md.
    Compression: two-phase strategy when context approaches budget.

    Compression triggers:
    1. Manual: /compress command (force=True)
    2. API error: ContextWindowExceeded → compress_on_context_error()
    3. Preventive: after each turn, if remaining < 5k tokens

    Two-phase compression:
    - Phase 1: Truncate long tool results and assistant messages (no LLM)
    - Phase 2: LLM generates structured task summary (only if phase 1 insufficient)
    """

    def __init__(
        self,
        config: MemoryConfig,
        model_client: ModelClient,
        on_compress_start: Callable[[], None] | None = None,
        on_compress: Callable[[int, int], None] | None = None,
        tracer: "SessionTracer | None" = None,
        embedder=None,  # agentkit.model.embedder.Embedder | None
    ):
        self._config = config
        self._model_client = model_client
        self.short_term = ShortTermMemory(config)
        self.long_term: LongTermMemory | None = None
        self._on_compress_start = on_compress_start  # callback() — show spinner
        self._on_compress = on_compress  # callback(before_tokens, after_tokens)
        self._tracer = tracer

        # Long-term memory requires embedding to be configured
        if config.long_term.enabled and embedder is not None and embedder.enabled:
            self.long_term = LongTermMemory(config.long_term, model_client, embedder=embedder)

        self._turns_since_extraction = 0

    def add_message(self, message: Message) -> None:
        """Add a message to the conversation log."""
        self.short_term.add_message(message)

    def add_messages(self, messages: list[Message]) -> None:
        """Add multiple messages to the conversation log."""
        self.short_term.add_messages(messages)

    def get_messages_for_llm(self) -> list[Message]:
        """Get messages to send to the LLM (context-window aware)."""
        return self.short_term.get_messages_for_llm()

    async def compress_if_needed(self, force: bool = False) -> bool:
        """Check if compression is needed and execute two-phase compression.

        Args:
            force: If True, compress regardless of budget (for /compress command).

        Returns True if compression was performed.
        """
        remaining = self._config.short_term_max_tokens - self.short_term.context_tokens

        if not force and remaining >= _REMAINING_THRESHOLD:
            return False

        return await self._execute_compression()

    async def compress_on_context_error(self) -> None:
        """Force compression after a ContextWindowExceeded error.

        Called by AgentLoop when the API rejects the request. Always executes
        regardless of current budget (since we know it's over).
        """
        await self._execute_compression()

    async def _execute_compression(self) -> bool:
        """Execute compression: truncate tool content → LLM summary → replace old context.

        Steps:
        1. Truncate long tool results / assistant messages (reduce LLM input cost)
        2. Send truncated older messages to LLM for structured task summary
        3. Replace older messages with the summary

        Returns True if compression was performed.
        """
        log = self.short_term.full_log
        if len(log) <= 2:
            return False

        import time as _time
        from agentkit.audit import audit as _audit
        # Extract long-term memory before compressing (context will be lost after)
        if self.long_term:
            try:
                await self.long_term.extract_and_update(log)
            except Exception:
                pass  # Don't block compression if extraction fails

        # Notify CLI to show spinner
        if self._on_compress_start:
            self._on_compress_start()

        before_tokens = self.short_term.context_tokens
        _compress_ts = _time.monotonic()
        _audit("memory.manager", "compress.start", data={"before_tokens": before_tokens})

        # ─── Step 1: Truncate long tool/assistant content (preprocessing) ───
        self.short_term.trim_for_compression()

        # ─── Step 2: LLM structured task compression ───
        last_turn_start = self.short_term._find_last_turn_start()
        older_messages = self.short_term.full_log[:last_turn_start]

        if not older_messages:
            # Only the current turn exists, nothing to compress
            return False

        # Format messages for the compression prompt
        conversation_text = self._format_for_compression(older_messages)
        prompt = COMPRESSION_PROMPT.format(conversation=conversation_text)

        summary_text = ""
        try:
            resp = await self._model_client.complete(
                [Message(role="user", content=prompt)],
                tools=None,
            )
            summary_text = resp.content.strip() if resp.content else ""
        except Exception:
            # Fallback: simple truncation if LLM fails
            summary_text = self._fallback_summary(older_messages)

        # ─── Step 3: Replace older messages with summary ───
        self.short_term.compress(summary_text, keep_recent_from=last_turn_start)

        after_tokens = self.short_term.context_tokens
        self._notify_and_trace(before_tokens, after_tokens, phase=2, llm_input=prompt, llm_output=summary_text)
        _audit("memory.manager", "compress.done",
               duration_ms=(_time.monotonic() - _compress_ts) * 1000,
               data={"before_tokens": before_tokens, "after_tokens": after_tokens,
                     "freed_tokens": before_tokens - after_tokens})
        from agentkit.events import emit_system_event
        emit_system_event(f"上下文已压缩（{before_tokens // 1000}k → {after_tokens // 1000}k），早期对话细节可能丢失")
        return True

    def _format_for_compression(self, messages: list[Message]) -> str:
        """Format messages into readable text for the compression prompt."""
        lines = []
        turn_num = 0
        for m in messages:
            if m.role == "user":
                turn_num += 1
            role_tag = {
                "user": f"[T{turn_num}] 用户",
                "assistant": f"[T{turn_num}] 助手",
                "system": "系统",
                "tool": f"[T{turn_num}] 工具",
            }.get(m.role, m.role)

            if m.role == "tool" and m.name:
                role_tag = f"[T{turn_num}] 工具({m.name})"

            content = m.content or ""
            if m.tool_calls:
                tc_info = ", ".join(tc.name for tc in m.tool_calls)
                lines.append(f"{role_tag}: {content} [调用工具: {tc_info}]")
            elif content:
                lines.append(f"{role_tag}: {content}")

        return "\n".join(lines)

    @staticmethod
    def _fallback_summary(messages: list[Message]) -> str:
        """Generate a simple fallback summary when LLM compression fails."""
        parts = []
        for m in messages:
            if m.role == "user" and m.content:
                parts.append(f"- 用户: {m.content[:100]}")
            elif m.role == "assistant" and m.content and not m.tool_calls:
                parts.append(f"- 助手: {m.content[:100]}")
        summary = "\n".join(parts[:20])
        return f"[对话摘要 — 压缩生成失败，以下为关键片段]\n{summary}"

    def _notify_and_trace(
        self,
        before_tokens: int,
        after_tokens: int,
        phase: int,
        llm_input: str | None,
        llm_output: str | None,
    ) -> None:
        """Notify CLI and record compression as an independent trace."""
        # Record as independent trace (not a child span of a turn)
        if self._tracer:
            trace_input = llm_input if llm_input else f"[Phase 1 trim] before={before_tokens}"
            trace_output = llm_output if llm_output else f"[Phase 1 trim] after={after_tokens}, freed={before_tokens - after_tokens}"
            span = self._tracer.start_turn(trace_input)
            span.span_type = "compression"
            span.attributes["phase"] = phase
            span.attributes["before_tokens"] = before_tokens
            span.attributes["after_tokens"] = after_tokens
            self._tracer.end_span(span, output=trace_output)

        # Notify CLI
        if self._on_compress:
            self._on_compress(before_tokens, after_tokens)

    async def on_turn_complete(self) -> None:
        """Called after each user turn completes. Checks compression + extraction."""
        self._turns_since_extraction += 1

        # Trigger #3: Preventive compression when remaining < threshold
        await self.compress_if_needed()

        if self._config.long_term.trigger == "every_n_turns":
            if self._turns_since_extraction >= self._config.long_term.trigger_value:
                await self.extract()
                self._turns_since_extraction = 0

    async def extract(self) -> dict[str, int] | None:
        """Force long-term memory extraction from the conversation log.

        Returns counts dict: {added, updated, deleted, skipped} or None if disabled.
        """
        if not self.long_term:
            return None

        log = self.short_term.full_log
        if not log:
            return None

        import time as _time
        from agentkit.audit import audit as _audit
        _ts = _time.monotonic()
        _audit("memory.manager", "extract.start", data={"messages": len(log)})
        try:
            counts = await self.long_term.extract_and_update(log)
            _audit("memory.manager", "extract.done",
                   duration_ms=(_time.monotonic() - _ts) * 1000, data=counts)
            from agentkit.events import emit_system_event
            _parts = []
            if counts and counts.get("added"):
                _parts.append(f"+{counts['added']} 条")
            if counts and counts.get("updated"):
                _parts.append(f"更新 {counts['updated']} 条")
            if counts and counts.get("deleted"):
                _parts.append(f"删除 {counts['deleted']} 条")
            if _parts:
                emit_system_event(f"长期记忆已更新（{'，'.join(_parts)}）")
        except Exception as e:
            _audit("memory.manager", "extract.error", status="error",
                   duration_ms=(_time.monotonic() - _ts) * 1000, error=str(e))
            from agentkit.events import emit_system_event
            emit_system_event(f"长期记忆提取失败：{e}")
            raise
        self._turns_since_extraction = 0
        return counts

    async def on_session_end(self) -> None:
        """Called when the session ends. Extracts if trigger is on_session_end."""
        if self._config.long_term.trigger == "on_session_end":
            await self.extract()

    def clear(self) -> None:
        """Clear the conversation log."""
        self.short_term.clear()
        self._turns_since_extraction = 0
