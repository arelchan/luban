"""Short-term memory: conversation log with token-based context management."""

from __future__ import annotations

from agentkit.config.models import MemoryConfig
from agentkit.model.types import Message


def estimate_tokens(messages: list[Message]) -> int:
    """Estimate token count for a list of messages.

    Uses ~2 chars per token as a rough estimate (works for mixed Chinese/English).
    Images are estimated at ~1000 tokens each.
    """
    total_chars = 0
    for m in messages:
        if m.content:
            if isinstance(m.content, str):
                total_chars += len(m.content)
            elif isinstance(m.content, list):
                for part in m.content:
                    # Support both ContentPart objects and raw dicts (from deserialized sessions)
                    if isinstance(part, dict):
                        ptype = part.get("type", "")
                        if ptype == "text" and part.get("text"):
                            total_chars += len(part["text"])
                        elif ptype == "image":
                            total_chars += 2000
                    else:
                        if part.type == "text" and part.text:
                            total_chars += len(part.text)
                        elif part.type == "image":
                            total_chars += 2000
        # Tool calls and metadata add overhead
        if m.tool_calls:
            for tc in m.tool_calls:
                total_chars += len(tc.name) + len(str(tc.arguments))
    return total_chars // 2


class ShortTermMemory:
    """Maintains the full conversation log with token-aware context management.

    - Full log: ALL messages in the session, never truncated (used for saving/extraction)
    - Context view: Messages that fit within token budget (sent to LLM)
    - System messages: Always included, never evicted
    - Compressed summary: When context overflows, older messages are compressed into a summary
    """

    def __init__(self, config: MemoryConfig):
        self._config = config
        self._system_messages: list[Message] = []
        self._conversation_log: list[Message] = []
        self._compressed_summary: Message | None = None  # Summary of evicted messages

    @property
    def turn_count(self) -> int:
        """Number of user turns in the conversation."""
        return sum(1 for m in self._conversation_log if m.role == "user")

    @property
    def full_log(self) -> list[Message]:
        """The full untruncated conversation log (for saving/extraction)."""
        return self._conversation_log

    @property
    def context_tokens(self) -> int:
        """Estimated token count of current context (what would be sent to LLM)."""
        msgs = self.get_messages_for_llm()
        return estimate_tokens(msgs)

    @property
    def max_context_tokens(self) -> int:
        """Max token budget from config."""
        return self._config.short_term_max_tokens

    @property
    def needs_compression(self) -> bool:
        """Whether context exceeds the token budget and needs compression."""
        return self.context_tokens > self.max_context_tokens

    def add_message(self, message: Message) -> None:
        """Add a message to the conversation log."""
        self._conversation_log.append(message)

    def add_messages(self, messages: list[Message]) -> None:
        """Add multiple messages to the conversation log."""
        self._conversation_log.extend(messages)

    def get_messages_for_llm(self) -> list[Message]:
        """Get messages to send to the LLM (system + compressed summary + conversation).

        All messages are included. If compression has occurred, a summary
        message replaces the evicted portion.
        """
        messages = list(self._system_messages)

        # Include compressed summary if any
        if self._compressed_summary:
            messages.append(self._compressed_summary)

        messages.extend(self._conversation_log)
        return messages

    def compress(self, summary_text: str, keep_recent: int | None = None, keep_recent_from: int | None = None) -> None:
        """Replace older messages with a compressed summary.

        Args:
            summary_text: LLM-generated summary of the evicted messages.
            keep_recent: Number of recent messages to keep intact (legacy).
            keep_recent_from: Index from which to keep messages (preferred).
                If provided, messages[keep_recent_from:] are kept.
        """
        if keep_recent_from is not None:
            split_idx = keep_recent_from
        elif keep_recent is not None:
            split_idx = len(self._conversation_log) - keep_recent
        else:
            split_idx = self._find_last_turn_start()

        if split_idx <= 0:
            return

        # Build new summary incorporating any previous summary
        prev = ""
        if self._compressed_summary and self._compressed_summary.content:
            prev = self._compressed_summary.content + "\n\n"

        self._compressed_summary = Message(
            role="system",
            content=f"[Context Summary — earlier conversation compressed]\n{prev}{summary_text}",
        )

        # Keep only messages from split_idx onwards
        self._conversation_log = self._conversation_log[split_idx:]

    def set_system_messages(self, messages: list[Message]) -> None:
        """Replace all system messages (used by context layer on file changes)."""
        self._system_messages = messages

    def get_system_messages(self) -> list[Message]:
        """Get current system messages."""
        return self._system_messages

    def clear(self) -> None:
        """Clear conversation log and compressed summary (keeps system messages)."""
        self._conversation_log.clear()
        self._compressed_summary = None

    def get_recent_log(self, n_messages: int | None = None) -> list[Message]:
        """Get recent conversation messages (for extraction)."""
        if n_messages is None:
            return list(self._conversation_log)
        return self._conversation_log[-n_messages:]

    def trim_for_compression(self) -> int:
        """Phase 1 compression: truncate long tool results and assistant messages in-place.

        Skips the last turn (last user message and all subsequent messages).
        Returns estimated tokens freed.
        """
        last_turn_start = self._find_last_turn_start()
        messages_to_trim = self._conversation_log[:last_turn_start]
        tokens_before = estimate_tokens(messages_to_trim)

        for msg in messages_to_trim:
            if not msg.content or not isinstance(msg.content, str):
                continue

            if msg.role == "tool" and len(msg.content) > 200:
                # Truncate long tool results
                name = msg.name or "tool"
                orig_len = len(msg.content)
                msg.content = f"[{name} 返回 {orig_len}字] {msg.content[:150]}..."

            elif msg.role == "assistant" and len(msg.content) > 500:
                # Truncate long assistant responses (only those without tool_calls — those are final answers)
                if not msg.tool_calls:
                    extra = len(msg.content) - 300
                    msg.content = msg.content[:300] + f"...[+{extra}字]"

        tokens_after = estimate_tokens(messages_to_trim)
        return tokens_before - tokens_after

    def _find_last_turn_start(self) -> int:
        """Find the index of the last user message (start of last turn).

        The last turn = last user message + all subsequent assistant/tool messages.
        """
        for i in range(len(self._conversation_log) - 1, -1, -1):
            if self._conversation_log[i].role == "user":
                return i
        return len(self._conversation_log)
