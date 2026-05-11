"""Tests for agentkit.orchestration — AgentLoop."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agentkit.config.models import OrchestrationConfig
from agentkit.model.client import ModelClient
from agentkit.model.types import Message, ModelResponse, StreamChunk, ToolCall
from agentkit.orchestration.loop import AgentLoop
from agentkit.tools.manager import ToolManager
from agentkit.tracing.collector import SessionTracer


class TestAgentLoop:
    def _make_loop(
        self,
        stream_responses: list[list[StreamChunk]] | None = None,
        tool_results: dict[str, str] | None = None,
        tracer: SessionTracer | None = None,
    ) -> AgentLoop:
        """Create an AgentLoop with mocked model and tools."""
        mock_model = MagicMock(spec=ModelClient)
        mock_tools = MagicMock(spec=ToolManager)

        # Default: single text response
        if stream_responses is None:
            stream_responses = [[StreamChunk(content_delta="Hello!", is_final=True)]]

        # Make stream() an async generator
        call_count = [0]

        async def mock_stream(*args, **kwargs):
            idx = min(call_count[0], len(stream_responses) - 1)
            for chunk in stream_responses[idx]:
                yield chunk
            call_count[0] += 1

        mock_model.stream = mock_stream
        mock_model._config = MagicMock()
        mock_model._config.default = "anthropic/claude-test"
        mock_model.last_usage = None

        # Tool schemas
        mock_tools.get_tool_schemas.return_value = [
            {"type": "function", "function": {"name": "calc", "description": "Calculate", "parameters": {}}},
        ]

        # Tool execution
        async def mock_execute(name, args):
            if tool_results and name in tool_results:
                return tool_results[name]
            return f"result of {name}"

        mock_tools.execute_tool = mock_execute

        config = OrchestrationConfig(max_iterations=5)
        loop = AgentLoop(
            model_client=mock_model,
            tool_manager=mock_tools,
            config=config,
            tracer=tracer,
        )
        return loop

    @pytest.mark.asyncio
    async def test_simple_text_response(self):
        loop = self._make_loop()
        messages = [Message(role="user", content="hi")]
        text, new_msgs = await loop.run(messages)
        assert text == "Hello!"
        assert len(new_msgs) == 1
        assert new_msgs[0].role == "assistant"
        assert new_msgs[0].content == "Hello!"

    @pytest.mark.asyncio
    async def test_tool_call_then_response(self):
        # First response: tool call
        tc = ToolCall(id="tc1", name="calc", arguments={"expression": "2+2"})
        stream1 = [
            StreamChunk(content_delta="Let me calculate.", is_final=False),
            StreamChunk(is_final=True, tool_calls_delta=[tc]),
        ]
        # Second response: text
        stream2 = [StreamChunk(content_delta="The answer is 4.", is_final=True)]

        loop = self._make_loop(
            stream_responses=[stream1, stream2],
            tool_results={"calc": "4"},
        )

        messages = [Message(role="user", content="what is 2+2?")]
        text, new_msgs = await loop.run(messages)

        assert text == "The answer is 4."
        # assistant (with tool call) + tool result + assistant (final)
        assert len(new_msgs) == 3
        assert new_msgs[0].role == "assistant"
        assert new_msgs[0].tool_calls[0].name == "calc"
        assert new_msgs[1].role == "tool"
        assert new_msgs[1].content == "4"
        assert new_msgs[2].role == "assistant"
        assert new_msgs[2].content == "The answer is 4."

    @pytest.mark.asyncio
    async def test_max_iterations(self):
        # Always return tool calls → should hit max_iterations
        tc = ToolCall(id="tc1", name="calc", arguments={})
        stream_with_tool = [StreamChunk(is_final=True, tool_calls_delta=[tc])]

        loop = self._make_loop(stream_responses=[stream_with_tool] * 10)
        messages = [Message(role="user", content="loop forever")]
        text, new_msgs = await loop.run(messages)

        assert "Max iterations" in text

    @pytest.mark.asyncio
    async def test_stream_callback(self):
        chunks_received = []

        loop = self._make_loop(stream_responses=[
            [StreamChunk(content_delta="A"), StreamChunk(content_delta="B"), StreamChunk(is_final=True)],
        ])
        loop._on_stream_delta = lambda d: chunks_received.append(d)

        messages = [Message(role="user", content="hi")]
        await loop.run(messages)

        assert chunks_received == ["A", "B"]

    @pytest.mark.asyncio
    async def test_tool_callbacks(self):
        starts = []
        ends = []

        tc = ToolCall(id="tc1", name="calc", arguments={"expression": "1+1"})
        stream1 = [StreamChunk(is_final=True, tool_calls_delta=[tc])]
        stream2 = [StreamChunk(content_delta="done", is_final=True)]

        loop = self._make_loop(
            stream_responses=[stream1, stream2],
            tool_results={"calc": "2"},
        )
        loop._on_tool_start = lambda name, args: starts.append((name, args))
        loop._on_tool_end = lambda name, result: ends.append((name, result))

        messages = [Message(role="user", content="calc")]
        await loop.run(messages)

        assert len(starts) == 1
        assert starts[0][0] == "calc"
        assert len(ends) == 1
        assert ends[0][1] == "2"

    @pytest.mark.asyncio
    async def test_tracing_integration(self):
        tracer = SessionTracer()

        tc = ToolCall(id="tc1", name="calc", arguments={"expression": "3*3"})
        stream1 = [StreamChunk(content_delta="", is_final=True, tool_calls_delta=[tc])]
        stream2 = [StreamChunk(content_delta="9", is_final=True)]

        loop = self._make_loop(
            stream_responses=[stream1, stream2],
            tool_results={"calc": "9"},
            tracer=tracer,
        )

        messages = [Message(role="user", content="3 times 3")]
        await loop.run(messages)

        turns = tracer.get_turns()
        assert len(turns) == 1
        turn = turns[0]
        assert turn["span"]["input"] == "3 times 3"
        assert turn["span"]["output"] == "9"
        assert turn["span"]["status"] == "ok"

        children = turn["children"]
        # 2 LLM spans + 1 tool span
        assert len(children) == 3
        types = [c["span"]["span_type"] for c in children]
        assert "llm" in types
        assert "tool" in types

    @pytest.mark.asyncio
    async def test_tracing_none_is_noop(self):
        loop = self._make_loop(tracer=None)
        messages = [Message(role="user", content="hi")]
        text, _ = await loop.run(messages)
        assert text == "Hello!"  # Works fine without tracer

    @pytest.mark.asyncio
    async def test_tool_error_handling(self):
        tc = ToolCall(id="tc1", name="failing_tool", arguments={})
        stream1 = [StreamChunk(is_final=True, tool_calls_delta=[tc])]
        stream2 = [StreamChunk(content_delta="recovered", is_final=True)]

        mock_model = MagicMock(spec=ModelClient)
        mock_tools = MagicMock(spec=ToolManager)

        call_count = [0]

        async def mock_stream(*args, **kwargs):
            idx = min(call_count[0], 1)
            for chunk in [stream1, stream2][idx]:
                yield chunk
            call_count[0] += 1

        mock_model.stream = mock_stream
        mock_model._config = MagicMock()
        mock_model._config.default = "test"
        mock_model.last_usage = None
        mock_tools.get_tool_schemas.return_value = []

        async def mock_execute(name, args):
            raise ValueError("Tool exploded")

        mock_tools.execute_tool = mock_execute

        config = OrchestrationConfig(max_iterations=5)
        loop = AgentLoop(model_client=mock_model, tool_manager=mock_tools, config=config)

        messages = [Message(role="user", content="do something")]
        text, new_msgs = await loop.run(messages)

        # Tool error is captured as a tool message
        tool_msg = next(m for m in new_msgs if m.role == "tool")
        assert "Error executing" in tool_msg.content
        assert "Tool exploded" in tool_msg.content
