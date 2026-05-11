"""Core types for the model layer."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal


@dataclass
class Message:
    """A single message in the conversation."""

    role: Literal["system", "user", "assistant", "tool"]
    content: str | None = None
    tool_calls: list[ToolCall] = field(default_factory=list)
    tool_call_id: str | None = None  # For tool result messages
    name: str | None = None  # Tool name for tool result messages

    def to_litellm_dict(self) -> dict[str, Any]:
        """Convert to LiteLLM-compatible message dict."""
        msg: dict[str, Any] = {"role": self.role}

        if self.role == "tool":
            msg["content"] = self.content or ""
            msg["tool_call_id"] = self.tool_call_id
            if self.name:
                msg["name"] = self.name
        elif self.role == "assistant" and self.tool_calls:
            msg["content"] = self.content or ""
            msg["tool_calls"] = [tc.to_litellm_dict() for tc in self.tool_calls]
        else:
            msg["content"] = self.content or ""

        return msg


@dataclass
class ToolCall:
    """A tool call requested by the model."""

    id: str
    name: str
    arguments: dict[str, Any]

    def to_litellm_dict(self) -> dict[str, Any]:
        """Convert to LiteLLM tool_call format."""
        import json

        return {
            "id": self.id,
            "type": "function",
            "function": {
                "name": self.name,
                "arguments": json.dumps(self.arguments, ensure_ascii=False),
            },
        }


@dataclass
class StreamChunk:
    """A chunk of streamed response."""

    content_delta: str = ""
    is_final: bool = False
    tool_calls_delta: list[ToolCall] | None = None


@dataclass
class ModelResponse:
    """Complete response from the model."""

    content: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)
    usage: TokenUsage | None = None
    stop_reason: str | None = None


@dataclass
class TokenUsage:
    """Token usage information."""

    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    cache_creation_tokens: int = 0
    cache_read_tokens: int = 0
