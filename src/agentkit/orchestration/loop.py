"""Core Agent Loop — the think-act-observe cycle."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from agentkit.config.models import OrchestrationConfig
from agentkit.model.client import ContextWindowExceeded, ModelClient
from agentkit.model.types import Message, ModelResponse, StreamChunk, ToolCall
from agentkit.orchestration.reminders import ReminderEngine
from agentkit.tools.manager import ToolManager
from agentkit.tracing.collector import SessionTracer


class AgentLoop:
    """The think-act-observe loop. Heart of the framework.

    Flow:
    1. User message → add to messages
    2. Send messages + tool schemas to LLM
    3. If LLM returns text only → done, return text
    4. If LLM returns tool_calls → execute tools → add results → go to 2
    5. If max_iterations exceeded → force stop
    """

    def __init__(
        self,
        model_client: ModelClient,
        tool_manager: ToolManager,
        config: OrchestrationConfig,
        on_stream_delta: Callable[[str], None] | None = None,
        on_tool_start: Callable[[str, dict[str, Any]], None] | None = None,
        on_tool_end: Callable[[str, str], None] | None = None,
        tracer: SessionTracer | None = None,
        memory_manager: Any | None = None,
    ):
        self._model = model_client
        self._tools = tool_manager
        self._config = config
        self._on_stream_delta = on_stream_delta
        self._on_tool_start = on_tool_start
        self._on_tool_end = on_tool_end
        self._tracer = tracer
        self._memory_manager = memory_manager
        self._reminders = ReminderEngine()

    async def run(self, messages: list[Message]) -> tuple[str, list[Message]]:
        """Run the agent loop on a list of messages.

        Args:
            messages: Current conversation messages (including new user message).

        Returns:
            Tuple of (final assistant text, new messages generated in this turn).
            The caller is responsible for adding these to the conversation history.
        """
        import time as _time
        from agentkit.audit import audit as _audit
        new_messages: list[Message] = []
        tool_schemas = self._tools.get_tool_schemas()

        # Extract user input text for tracing (last user message)
        user_input = ""
        for m in reversed(messages):
            if m.role == "user":
                user_input = m.content or ""
                break

        _turn_ts = _time.monotonic()
        _audit("agent.loop", "turn.start", data={"input_preview": user_input[:100]})

        # Start turn span
        turn_span = self._tracer.start_turn(user_input) if self._tracer else None

        for iteration in range(self._config.max_iterations):
            # Build full message list (existing + new from this turn)
            all_messages = messages + new_messages

            # --- LLM span ---
            llm_span = None
            if self._tracer and turn_span:
                model_name = self._model._config.default
                llm_input = {
                    "messages": [m.to_litellm_dict() for m in all_messages],
                    "tools": tool_schemas if tool_schemas else None,
                    "model": model_name,
                }
                llm_span = self._tracer.start_span(
                    "llm",
                    parent=turn_span,
                    input=llm_input,
                    attributes={"model": model_name},
                )

            # Stream LLM response (with context-window retry)
            _llm_ts = _time.monotonic()
            _audit("agent.loop", "llm.call", data={"model": self._model._config.default, "iteration": iteration})
            try:
                response = await self._stream_completion(all_messages, tool_schemas)
            except ContextWindowExceeded:
                _audit("agent.loop", "llm.context_exceeded", status="warn",
                       data={"action": "compress_and_retry"})
                # Compress and retry once
                if self._memory_manager:
                    if self._tracer and llm_span:
                        self._tracer.end_span(llm_span, output={"error": "context_window_exceeded, retrying after compression"}, status="error")
                    await self._memory_manager.compress_on_context_error()
                    # Rebuild messages after compression
                    all_messages = self._memory_manager.get_messages_for_llm() + new_messages
                    # New LLM span for retry
                    if self._tracer and turn_span:
                        llm_span = self._tracer.start_span(
                            "llm",
                            parent=turn_span,
                            input={
                                "messages": [m.to_litellm_dict() for m in all_messages],
                                "tools": tool_schemas if tool_schemas else None,
                                "model": self._model._config.default,
                                "retry_after_compression": True,
                            },
                            attributes={"model": self._model._config.default},
                        )
                    response = await self._stream_completion(all_messages, tool_schemas)
                else:
                    raise
            except Exception as e:
                _audit("agent.loop", "llm.error", status="error", error=str(e),
                       duration_ms=(_time.monotonic() - _llm_ts) * 1000)
                from agentkit.events import emit_system_event
                emit_system_event(f"LLM 请求失败：{e}")
                if self._tracer and llm_span:
                    self._tracer.end_span(llm_span, output={"error": str(e)}, status="error")
                if self._tracer and turn_span:
                    self._tracer.end_span(turn_span, output={"error": str(e)}, status="error")
                raise

            _llm_ms = (_time.monotonic() - _llm_ts) * 1000
            _usage = response.usage
            _audit("agent.loop", "llm.done", duration_ms=_llm_ms, data={
                "tool_calls": [tc.name for tc in response.tool_calls] if response.tool_calls else [],
                "prompt_tokens": _usage.prompt_tokens if _usage else None,
                "completion_tokens": _usage.completion_tokens if _usage else None,
            })

            if self._tracer and llm_span:
                llm_output: dict[str, Any] = {"content": response.content}
                if response.tool_calls:
                    llm_output["tool_calls"] = [
                        {"id": tc.id, "name": tc.name, "arguments": tc.arguments}
                        for tc in response.tool_calls
                    ]
                if response.usage:
                    llm_output["usage"] = {
                        "prompt_tokens": response.usage.prompt_tokens,
                        "completion_tokens": response.usage.completion_tokens,
                        "total_tokens": response.usage.total_tokens,
                        "cache_creation_tokens": response.usage.cache_creation_tokens,
                        "cache_read_tokens": response.usage.cache_read_tokens,
                    }
                self._tracer.end_span(llm_span, output=llm_output)

            # Add assistant message
            assistant_msg = Message(
                role="assistant",
                content=response.content,
                tool_calls=response.tool_calls,
            )
            new_messages.append(assistant_msg)

            # If no tool calls, we're done
            if not response.tool_calls:
                if self._tracer and turn_span:
                    self._tracer.end_span(turn_span, output=response.content)
                _audit("agent.loop", "turn.end", duration_ms=(_time.monotonic() - _turn_ts) * 1000)
                return response.content, new_messages

            # Execute tool calls in parallel (independent tools benefit from concurrency)
            import asyncio as _asyncio

            async def _exec_one(tc: ToolCall):
                if self._on_tool_start:
                    self._on_tool_start(tc.name, tc.arguments)

                # --- Tool span ---
                tool_span = None
                if self._tracer and turn_span:
                    tool_span = self._tracer.start_span(
                        "tool",
                        parent=turn_span,
                        input={"name": tc.name, "arguments": tc.arguments},
                        attributes={"tool_name": tc.name},
                    )

                _tool_ts = _time.monotonic()
                _audit("agent.loop", "tool.call", data={"name": tc.name})
                try:
                    from agentkit.tools.builtin import _runtime_context as _rtc
                    if tool_span:
                        _rtc["current_tool_span"] = tool_span
                    result = await self._tools.execute_tool(tc.name, tc.arguments)
                    _rtc.pop("current_tool_span", None)
                    if self._tracer and tool_span:
                        self._tracer.end_span(tool_span, output={"result": result})
                    _audit("agent.loop", "tool.done", duration_ms=(_time.monotonic() - _tool_ts) * 1000,
                           data={"name": tc.name, "result_len": len(result)})
                except Exception as e:
                    from agentkit.tools.builtin import _runtime_context as _rtc
                    _rtc.pop("current_tool_span", None)
                    result = f"Error executing {tc.name}: {type(e).__name__}: {e}"
                    if self._tracer and tool_span:
                        self._tracer.end_span(tool_span, output={"error": result}, status="error")
                    _audit("agent.loop", "tool.error", status="error",
                           duration_ms=(_time.monotonic() - _tool_ts) * 1000,
                           data={"name": tc.name}, error=str(e))

                if self._on_tool_end:
                    self._on_tool_end(tc.name, result)
                return tc, result

            # Run all tool calls concurrently
            tool_results = await _asyncio.gather(
                *[_exec_one(tc) for tc in response.tool_calls]
            )

            # Add tool result messages in original order (with system reminders)
            _reminder_ctx = {}
            if self._memory_manager:
                _remaining = (
                    self._memory_manager._config.short_term_max_tokens
                    - self._memory_manager.short_term.context_tokens
                )
                _reminder_ctx["remaining_tokens"] = _remaining

            _MAX_TOOL_RESULT_CHARS = 30000  # Hard cap to prevent context blowup

            for tc, result in tool_results:
                # Hard truncation for overly long results
                if len(result) > _MAX_TOOL_RESULT_CHARS:
                    result = result[:_MAX_TOOL_RESULT_CHARS] + \
                        f"\n\n[TRUNCATED: result was {len(result)} chars, showing first {_MAX_TOOL_RESULT_CHARS}. Use offset/limit params to read specific sections.]"
                # Post-process: append conditional system reminders
                result = self._reminders.process(tc.name, result, context=_reminder_ctx)
                tool_msg = Message(
                    role="tool",
                    content=result,
                    tool_call_id=tc.id,
                    name=tc.name,
                )
                new_messages.append(tool_msg)

        # Max iterations reached
        from agentkit import APP_NAME
        from datetime import datetime as _dt
        final_text = f"[{APP_NAME}] Max iterations reached."
        _ts_str = _dt.now().strftime("%Y-%m-%d %H:%M")
        new_messages.append(Message(
            role="user",
            content=f"[SYSTEM {_ts_str}] 达到最大迭代次数（{self._config.max_iterations}），本轮强制结束",
        ))
        if self._tracer and turn_span:
            self._tracer.end_span(turn_span, output=final_text, status="error")
        _audit("agent.loop", "turn.max_iterations", status="warn",
               data={"max": self._config.max_iterations},
               duration_ms=(_time.monotonic() - _turn_ts) * 1000)
        return final_text, new_messages

    async def _stream_completion(
        self, messages: list[Message], tools: list[dict[str, Any]]
    ) -> ModelResponse:
        """Stream LLM response, calling callbacks for each chunk."""
        full_content = ""
        final_tool_calls: list[ToolCall] = []

        async for chunk in self._model.stream(
            messages=messages,
            tools=tools if tools else None,
        ):
            # Stream text to callback
            if chunk.content_delta and self._on_stream_delta:
                self._on_stream_delta(chunk.content_delta)
            if chunk.content_delta:
                full_content += chunk.content_delta

            # Collect tool calls from final chunk
            if chunk.is_final and chunk.tool_calls_delta:
                final_tool_calls = chunk.tool_calls_delta

        return ModelResponse(content=full_content, tool_calls=final_tool_calls, usage=self._model.last_usage)
