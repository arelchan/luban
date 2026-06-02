"""Core types for the model layer."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal


@dataclass
class ContentPart:
    """A single content part in a multimodal message."""

    type: Literal["text", "image", "video", "audio"] = "text"
    text: str | None = None           # type="text"
    media_type: str | None = None     # "image/png", "video/mp4", "audio/mpeg", etc.
    data: str | None = None           # base64 encoded data
    source_url: str | None = None     # original URL (preserved for API URL mode)

    def to_openai_dict(self) -> dict[str, Any]:
        """Convert to OpenAI content part format."""
        if self.type == "text":
            return {"type": "text", "text": self.text or ""}
        if self.type == "image":
            if self.source_url:
                return {"type": "image_url", "image_url": {"url": self.source_url}}
            return {"type": "image_url", "image_url": {"url": f"data:{self.media_type};base64,{self.data}"}}
        # video / audio — use input_audio/input_video for OpenAI format, fallback to data URL
        if self.source_url:
            return {"type": "image_url", "image_url": {"url": self.source_url}}
        return {"type": "image_url", "image_url": {"url": f"data:{self.media_type};base64,{self.data}"}}

    def to_anthropic_dict(self) -> dict[str, Any]:
        """Convert to Anthropic content block format."""
        if self.type == "text":
            return {"type": "text", "text": self.text or ""}
        # image / video / audio — Anthropic uses the same block structure
        block_type = self.type if self.type == "image" else self.type
        if self.source_url:
            return {"type": block_type, "source": {"type": "url", "url": self.source_url}}
        return {"type": block_type, "source": {"type": "base64", "media_type": self.media_type, "data": self.data}}


@dataclass
class Message:
    """A single message in the conversation."""

    role: Literal["system", "user", "assistant", "tool"]
    content: str | list[ContentPart] | None = None
    tool_calls: list[ToolCall] = field(default_factory=list)
    tool_call_id: str | None = None  # For tool result messages
    name: str | None = None  # Tool name for tool result messages

    @property
    def text_content(self) -> str:
        """Get text-only content (for display, compression, etc.)."""
        if self.content is None:
            return ""
        if isinstance(self.content, str):
            return self.content
        parts = []
        for p in self.content:
            if isinstance(p, dict):
                if p.get("type") == "text" and p.get("text"):
                    parts.append(p["text"])
            elif p.type == "text" and p.text:
                parts.append(p.text)
        return "\n".join(parts)

    def to_litellm_dict(self) -> dict[str, Any]:
        """Convert to LiteLLM-compatible message dict."""
        msg: dict[str, Any] = {"role": self.role}

        if self.role == "tool":
            msg["content"] = self._serialize_content_str()
            msg["tool_call_id"] = self.tool_call_id
            if self.name:
                msg["name"] = self.name
        elif self.role == "assistant" and self.tool_calls:
            msg["content"] = self._serialize_content_str()
            msg["tool_calls"] = [
                tc if isinstance(tc, dict) else tc.to_litellm_dict()
                for tc in self.tool_calls
            ]
        else:
            msg["content"] = self._serialize_content()

        return msg

    def _serialize_content(self) -> str | list[dict[str, Any]]:
        """Serialize content — returns list for multimodal, str for text-only."""
        if self.content is None:
            return ""
        if isinstance(self.content, str):
            return self.content
        # Multimodal content parts (handle both ContentPart objects and raw dicts)
        result = []
        for p in self.content:
            if isinstance(p, dict):
                result.append(p)  # Already serialized
            else:
                result.append(p.to_openai_dict())
        return result

    def _serialize_content_str(self) -> str:
        """Serialize content as plain string (for tool/assistant roles)."""
        if self.content is None:
            return ""
        if isinstance(self.content, str):
            return self.content
        return self.text_content


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
