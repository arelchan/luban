"""Tests for agentkit.model.types — Message, ToolCall, StreamChunk, ModelResponse, TokenUsage."""

from __future__ import annotations

import json

from agentkit.model.types import Message, ModelResponse, StreamChunk, TokenUsage, ToolCall


# ─── Message ───


class TestMessage:
    def test_user_message(self):
        msg = Message(role="user", content="hello")
        assert msg.role == "user"
        assert msg.content == "hello"
        assert msg.tool_calls == []
        assert msg.tool_call_id is None

    def test_system_message(self):
        msg = Message(role="system", content="You are helpful.")
        assert msg.role == "system"

    def test_assistant_message_with_tool_calls(self):
        tc = ToolCall(id="tc1", name="calc", arguments={"expression": "1+1"})
        msg = Message(role="assistant", content="Let me calc.", tool_calls=[tc])
        assert len(msg.tool_calls) == 1
        assert msg.tool_calls[0].name == "calc"

    def test_tool_message(self):
        msg = Message(role="tool", content="result=2", tool_call_id="tc1", name="calc")
        assert msg.role == "tool"
        assert msg.tool_call_id == "tc1"
        assert msg.name == "calc"

    def test_to_litellm_dict_user(self):
        msg = Message(role="user", content="hi")
        d = msg.to_litellm_dict()
        assert d == {"role": "user", "content": "hi"}

    def test_to_litellm_dict_tool(self):
        msg = Message(role="tool", content="ok", tool_call_id="tc1", name="calc")
        d = msg.to_litellm_dict()
        assert d["role"] == "tool"
        assert d["tool_call_id"] == "tc1"
        assert d["name"] == "calc"
        assert d["content"] == "ok"

    def test_to_litellm_dict_assistant_with_tool_calls(self):
        tc = ToolCall(id="tc1", name="calc", arguments={"x": 1})
        msg = Message(role="assistant", content="", tool_calls=[tc])
        d = msg.to_litellm_dict()
        assert d["role"] == "assistant"
        assert len(d["tool_calls"]) == 1
        assert d["tool_calls"][0]["function"]["name"] == "calc"

    def test_to_litellm_dict_none_content_becomes_empty(self):
        msg = Message(role="user", content=None)
        d = msg.to_litellm_dict()
        assert d["content"] == ""


# ─── ToolCall ───


class TestToolCall:
    def test_basic(self):
        tc = ToolCall(id="tc1", name="read_file", arguments={"file_path": "/tmp/a.txt"})
        assert tc.id == "tc1"
        assert tc.name == "read_file"
        assert tc.arguments["file_path"] == "/tmp/a.txt"

    def test_to_litellm_dict(self):
        tc = ToolCall(id="tc1", name="calc", arguments={"expression": "3*4"})
        d = tc.to_litellm_dict()
        assert d["id"] == "tc1"
        assert d["type"] == "function"
        assert d["function"]["name"] == "calc"
        args = json.loads(d["function"]["arguments"])
        assert args["expression"] == "3*4"

    def test_to_litellm_dict_empty_arguments(self):
        tc = ToolCall(id="tc1", name="get_time", arguments={})
        d = tc.to_litellm_dict()
        assert json.loads(d["function"]["arguments"]) == {}


# ─── StreamChunk ───


class TestStreamChunk:
    def test_defaults(self):
        c = StreamChunk()
        assert c.content_delta == ""
        assert c.is_final is False
        assert c.tool_calls_delta is None

    def test_text_chunk(self):
        c = StreamChunk(content_delta="Hello", is_final=False)
        assert c.content_delta == "Hello"

    def test_final_chunk_with_tool_calls(self):
        tc = ToolCall(id="tc1", name="calc", arguments={"expression": "1"})
        c = StreamChunk(is_final=True, tool_calls_delta=[tc])
        assert c.is_final
        assert len(c.tool_calls_delta) == 1


# ─── ModelResponse ───


class TestModelResponse:
    def test_text_only(self):
        r = ModelResponse(content="Hello!")
        assert r.content == "Hello!"
        assert r.tool_calls == []
        assert r.usage is None

    def test_with_usage(self):
        r = ModelResponse(
            content="ok",
            usage=TokenUsage(prompt_tokens=10, completion_tokens=5, total_tokens=15),
        )
        assert r.usage.prompt_tokens == 10
        assert r.usage.total_tokens == 15

    def test_with_tool_calls(self):
        tc = ToolCall(id="tc1", name="calc", arguments={})
        r = ModelResponse(content="", tool_calls=[tc])
        assert len(r.tool_calls) == 1


# ─── TokenUsage ───


class TestTokenUsage:
    def test_defaults(self):
        u = TokenUsage()
        assert u.prompt_tokens == 0
        assert u.completion_tokens == 0
        assert u.total_tokens == 0

    def test_values(self):
        u = TokenUsage(prompt_tokens=100, completion_tokens=50, total_tokens=150)
        assert u.total_tokens == 150
