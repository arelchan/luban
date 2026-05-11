"""Tests for agentkit.model.client — ModelClient parsing and request building."""

from __future__ import annotations

import json

import pytest

from agentkit.config.models import ModelConfig, ModelOptions, ProviderConfig
from agentkit.model.client import ModelClient
from agentkit.model.types import Message, ToolCall


# ─── Request building ───


class TestBuildDirectRequest:
    def _make_client(self, **kwargs) -> ModelClient:
        config = ModelConfig(
            default="anthropic/claude-sonnet-4-20250514",
            base_url="https://proxy.test/api",
            api_keys={"anthropic": "sk-test"},
            **kwargs,
        )
        return ModelClient(config)

    def test_anthropic_url_and_headers(self):
        client = self._make_client()
        url, headers, body = client._build_direct_request(
            [Message(role="user", content="hi")], None, None
        )
        assert url == "https://proxy.test/api/v1/messages"
        assert "anthropic-version" in headers
        assert headers["Authorization"] == "Bearer sk-test"

    def test_anthropic_body_basic(self):
        client = self._make_client()
        _, _, body = client._build_direct_request(
            [Message(role="user", content="hi")], None, None
        )
        assert body["model"] == "claude-sonnet-4-20250514"
        assert body["max_tokens"] == 4096
        assert body["temperature"] == 0.7
        assert len(body["messages"]) == 1
        assert body["messages"][0] == {"role": "user", "content": "hi"}

    def test_anthropic_system_message_extracted(self):
        client = self._make_client()
        messages = [
            Message(role="system", content="You are helpful."),
            Message(role="user", content="hi"),
        ]
        _, _, body = client._build_direct_request(messages, None, None)
        assert body["system"] == "You are helpful."
        assert len(body["messages"]) == 1  # Only user message in messages array

    def test_anthropic_thinking_mode(self):
        client = self._make_client(options=ModelOptions(thinking=True, thinking_budget=5000))
        _, _, body = client._build_direct_request(
            [Message(role="user", content="hi")], None, None
        )
        assert body["temperature"] == 1  # Required for thinking
        assert body["thinking"]["type"] == "enabled"
        assert body["thinking"]["budget_tokens"] == 5000

    def test_anthropic_non_thinking_mode(self):
        client = self._make_client(options=ModelOptions(thinking=False, temperature=0.5))
        _, _, body = client._build_direct_request(
            [Message(role="user", content="hi")], None, None
        )
        assert body["temperature"] == 0.5
        assert "thinking" not in body

    def test_anthropic_tool_conversion(self):
        client = self._make_client()
        tools = [{
            "type": "function",
            "function": {
                "name": "calc",
                "description": "Calculate",
                "parameters": {"type": "object", "properties": {"expr": {"type": "string"}}},
            },
        }]
        _, _, body = client._build_direct_request(
            [Message(role="user", content="hi")], tools, None
        )
        assert len(body["tools"]) == 1
        assert body["tools"][0]["name"] == "calc"
        assert body["tools"][0]["description"] == "Calculate"
        assert body["tools"][0]["input_schema"]["properties"]["expr"]["type"] == "string"

    def test_anthropic_tool_message_format(self):
        client = self._make_client()
        messages = [
            Message(role="user", content="calc 2+2"),
            Message(
                role="assistant", content="",
                tool_calls=[ToolCall(id="tc1", name="calc", arguments={"expression": "2+2"})],
            ),
            Message(role="tool", content="4", tool_call_id="tc1"),
        ]
        _, _, body = client._build_direct_request(messages, None, None)
        # Assistant message with tool_use
        assert body["messages"][1]["role"] == "assistant"
        assert body["messages"][1]["content"][0]["type"] == "tool_use"
        # Tool result as user message with tool_result
        assert body["messages"][2]["role"] == "user"
        assert body["messages"][2]["content"][0]["type"] == "tool_result"
        assert body["messages"][2]["content"][0]["tool_use_id"] == "tc1"

    def test_stream_flag(self):
        client = self._make_client()
        _, _, body = client._build_direct_request(
            [Message(role="user", content="hi")], None, None, stream=True
        )
        assert body["stream"] is True

    def test_openai_provider(self):
        config = ModelConfig(
            default="openai/gpt-4o",
            base_url="https://proxy.test/api",
            api_keys={"openai": "sk-test"},
        )
        client = ModelClient(config)
        url, headers, body = client._build_direct_request(
            [Message(role="user", content="hi")], None, None
        )
        assert url == "https://proxy.test/api/v1/chat/completions"
        assert body["model"] == "gpt-4o"


# ─── Response parsing ───


class TestParseAnthropicResponse:
    def _make_client(self) -> ModelClient:
        config = ModelConfig(default="anthropic/claude", base_url="https://test")
        return ModelClient(config)

    def test_text_response(self):
        client = self._make_client()
        data = {
            "content": [{"type": "text", "text": "Hello!"}],
            "usage": {"input_tokens": 10, "output_tokens": 5},
            "stop_reason": "end_turn",
        }
        resp = client._parse_anthropic_response(data)
        assert resp.content == "Hello!"
        assert resp.usage.prompt_tokens == 10
        assert resp.usage.completion_tokens == 5
        assert resp.stop_reason == "end_turn"

    def test_tool_use_response(self):
        client = self._make_client()
        data = {
            "content": [
                {"type": "text", "text": "Let me calculate."},
                {"type": "tool_use", "id": "tc1", "name": "calc", "input": {"expression": "2+2"}},
            ],
            "usage": {"input_tokens": 20, "output_tokens": 15},
        }
        resp = client._parse_anthropic_response(data)
        assert resp.content == "Let me calculate."
        assert len(resp.tool_calls) == 1
        assert resp.tool_calls[0].id == "tc1"
        assert resp.tool_calls[0].name == "calc"
        assert resp.tool_calls[0].arguments == {"expression": "2+2"}

    def test_no_usage(self):
        client = self._make_client()
        data = {"content": [{"type": "text", "text": "hi"}]}
        resp = client._parse_anthropic_response(data)
        assert resp.usage is None


# ─── Stream event parsing ───


class TestParseAnthropicStreamEvents:
    def _make_client(self) -> ModelClient:
        config = ModelConfig(default="anthropic/claude", base_url="https://test")
        return ModelClient(config)

    def test_message_start_with_usage(self):
        client = self._make_client()
        event = {"type": "message_start", "message": {"usage": {"input_tokens": 42}}}
        result = client._parse_anthropic_stream_event(event, {}, 0)
        assert result is None  # No chunk emitted
        assert client.total_input_tokens == 42

    def test_message_start_empty_usage(self):
        client = self._make_client()
        event = {"type": "message_start", "message": {"usage": {}}}
        result = client._parse_anthropic_stream_event(event, {}, 0)
        assert result is None
        assert client.total_input_tokens == 0

    def test_content_block_delta_text(self):
        client = self._make_client()
        event = {"type": "content_block_delta", "delta": {"type": "text_delta", "text": "Hello"}}
        chunk = client._parse_anthropic_stream_event(event, {}, 0)
        assert chunk is not None
        assert chunk.content_delta == "Hello"

    def test_content_block_start_tool_use(self):
        client = self._make_client()
        accumulated = {}
        event = {
            "type": "content_block_start",
            "index": 0,
            "content_block": {"type": "tool_use", "id": "tc1", "name": "calc"},
        }
        result = client._parse_anthropic_stream_event(event, accumulated, 0)
        assert result is None
        assert 0 in accumulated
        assert accumulated[0]["id"] == "tc1"
        assert accumulated[0]["name"] == "calc"

    def test_content_block_delta_tool_json(self):
        client = self._make_client()
        accumulated = {0: {"id": "tc1", "name": "calc", "arguments": ""}}
        event = {
            "type": "content_block_delta",
            "index": 0,
            "delta": {"type": "input_json_delta", "partial_json": '{"exp'},
        }
        result = client._parse_anthropic_stream_event(event, accumulated, 0)
        assert result is None
        assert accumulated[0]["arguments"] == '{"exp'

    def test_message_delta_with_both_tokens(self):
        client = self._make_client()
        event = {"type": "message_delta", "usage": {"input_tokens": 15, "output_tokens": 30}}
        result = client._parse_anthropic_stream_event(event, {}, 0)
        assert result is None
        assert client.total_input_tokens == 15
        assert client.total_output_tokens == 30

    def test_message_delta_output_only(self):
        client = self._make_client()
        event = {"type": "message_delta", "usage": {"output_tokens": 25}}
        result = client._parse_anthropic_stream_event(event, {}, 0)
        assert result is None
        assert client.total_output_tokens == 25
        assert client.total_input_tokens == 0

    def test_unknown_event_type(self):
        client = self._make_client()
        event = {"type": "ping"}
        result = client._parse_anthropic_stream_event(event, {}, 0)
        assert result is None


# ─── Token tracking ───


class TestTokenTracking:
    def test_initial_state(self):
        config = ModelConfig(default="anthropic/claude", base_url="https://test")
        client = ModelClient(config)
        assert client.total_input_tokens == 0
        assert client.total_output_tokens == 0
        assert client.last_usage is None

    def test_cumulative_tracking(self):
        config = ModelConfig(default="anthropic/claude", base_url="https://test")
        client = ModelClient(config)

        # Simulate message_start with input tokens
        client._parse_anthropic_stream_event(
            {"type": "message_start", "message": {"usage": {"input_tokens": 100}}}, {}, 0
        )
        # Simulate message_delta with output tokens
        client._parse_anthropic_stream_event(
            {"type": "message_delta", "usage": {"output_tokens": 50}}, {}, 0
        )
        # Another turn
        client._parse_anthropic_stream_event(
            {"type": "message_start", "message": {"usage": {"input_tokens": 200}}}, {}, 0
        )
        client._parse_anthropic_stream_event(
            {"type": "message_delta", "usage": {"output_tokens": 75}}, {}, 0
        )

        assert client.total_input_tokens == 300
        assert client.total_output_tokens == 125


# ─── Helper methods ───


class TestHelperMethods:
    def test_get_model_name_with_prefix(self):
        config = ModelConfig(default="anthropic/claude-sonnet-4-20250514")
        client = ModelClient(config)
        assert client._get_model_name() == "claude-sonnet-4-20250514"

    def test_get_model_name_without_prefix(self):
        config = ModelConfig(default="gpt-4o")
        client = ModelClient(config)
        assert client._get_model_name() == "gpt-4o"

    def test_get_provider_anthropic(self):
        config = ModelConfig(default="anthropic/claude")
        client = ModelClient(config)
        assert client._get_provider() == "anthropic"

    def test_get_provider_openai(self):
        config = ModelConfig(default="openai/gpt-4o")
        client = ModelClient(config)
        assert client._get_provider() == "openai"

    def test_get_provider_no_prefix(self):
        config = ModelConfig(default="some-model")
        client = ModelClient(config)
        assert client._get_provider() == "anthropic"  # Default

    def test_get_api_key(self):
        config = ModelConfig(api_keys={"anthropic": "sk-abc"})
        client = ModelClient(config)
        assert client._get_api_key() == "sk-abc"

    def test_get_api_key_empty(self):
        config = ModelConfig(api_keys={})
        client = ModelClient(config)
        assert client._get_api_key() is None


# ─── Multi-provider support ───


class TestMultiProvider:
    def _make_client(self) -> ModelClient:
        config = ModelConfig(
            default="aws.claude-sonnet-4.6",
            providers=[
                ProviderConfig(
                    name="meituan",
                    base_url="https://aigc.sankuai.com/v1/openai/native",
                    api_key="sk-mt-test",
                    format="openai",
                    models=["aws.claude-sonnet-4.6", "aws.claude-opus-4.6", "aws.claude-opus-4.7"],
                ),
            ],
        )
        return ModelClient(config)

    def test_resolve_provider_found(self):
        client = self._make_client()
        p = client._resolve_provider("aws.claude-opus-4.7")
        assert p is not None
        assert p.name == "meituan"

    def test_resolve_provider_not_found(self):
        client = self._make_client()
        p = client._resolve_provider("unknown-model")
        assert p is None

    def test_resolve_provider_default(self):
        client = self._make_client()
        p = client._resolve_provider()
        assert p is not None
        assert p.name == "meituan"

    def test_build_request_openai_format(self):
        client = self._make_client()
        url, headers, body = client._build_direct_request(
            [Message(role="user", content="hi")], None, None
        )
        assert url == "https://aigc.sankuai.com/v1/openai/native/chat/completions"
        assert headers["Authorization"] == "Bearer sk-mt-test"
        assert body["model"] == "aws.claude-sonnet-4.6"

    def test_build_request_switch_model(self):
        client = self._make_client()
        url, headers, body = client._build_direct_request(
            [Message(role="user", content="hi")], None, "aws.claude-opus-4.7"
        )
        assert url == "https://aigc.sankuai.com/v1/openai/native/chat/completions"
        assert body["model"] == "aws.claude-opus-4.7"

    def test_build_request_thinking_mode(self):
        config = ModelConfig(
            default="aws.claude-opus-4.7",
            providers=[
                ProviderConfig(
                    name="meituan",
                    base_url="https://aigc.sankuai.com/v1/openai/native",
                    api_key="sk-mt-test",
                    format="openai",
                    models=["aws.claude-opus-4.7"],
                ),
            ],
            options=ModelOptions(thinking=True, thinking_budget=1024),
        )
        client = ModelClient(config)
        _, _, body = client._build_direct_request(
            [Message(role="user", content="hi")], None, None
        )
        assert body["thinking"]["type"] == "enabled"
        assert body["thinking"]["budget_tokens"] == 1024
        assert "temperature" not in body

    def test_should_use_direct_with_providers(self):
        client = self._make_client()
        assert client._should_use_direct("aws.claude-opus-4.7") is True
        assert client._should_use_direct("unknown-model") is False

    def test_get_api_format(self):
        client = self._make_client()
        assert client._get_api_format("aws.claude-sonnet-4.6") == "openai"
        # Unknown model falls back to legacy logic
        assert client._get_api_format("anthropic/claude") == "anthropic"


class TestMultiProviderMultiple:
    """Test with multiple providers configured."""

    def _make_client(self) -> ModelClient:
        config = ModelConfig(
            default="aws.claude-sonnet-4.6",
            providers=[
                ProviderConfig(
                    name="anthropic-proxy",
                    base_url="https://proxy.example.com/v1/anthropic",
                    api_key="sk-ant",
                    format="anthropic",
                    models=["claude-sonnet"],
                ),
                ProviderConfig(
                    name="openai-proxy",
                    base_url="https://proxy.example.com/v1/openai",
                    api_key="sk-oai",
                    format="openai",
                    models=["aws.claude-sonnet-4.6", "gpt-4o"],
                ),
            ],
        )
        return ModelClient(config)

    def test_resolve_to_correct_provider(self):
        client = self._make_client()
        p = client._resolve_provider("claude-sonnet")
        assert p.name == "anthropic-proxy"
        p = client._resolve_provider("gpt-4o")
        assert p.name == "openai-proxy"

    def test_anthropic_format_provider(self):
        client = self._make_client()
        url, headers, body = client._build_direct_request(
            [Message(role="user", content="hi")], None, "claude-sonnet"
        )
        assert url == "https://proxy.example.com/v1/anthropic/v1/messages"
        assert "anthropic-version" in headers
        assert headers["Authorization"] == "Bearer sk-ant"

    def test_openai_format_provider(self):
        client = self._make_client()
        url, headers, body = client._build_direct_request(
            [Message(role="user", content="hi")], None, "gpt-4o"
        )
        assert url == "https://proxy.example.com/v1/openai/chat/completions"
        assert headers["Authorization"] == "Bearer sk-oai"
