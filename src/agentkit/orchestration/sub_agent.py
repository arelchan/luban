"""Sub-agent executor for tool-style spawning."""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Any

from agentkit.model.client import ModelClient
from agentkit.model.types import Message
from agentkit.tools.manager import ToolManager

if TYPE_CHECKING:
    from agentkit.tracing.collector import SessionTracer
    from agentkit.tracing.models import Span

_DEFAULT_MAX_ITERATIONS = 20  # matches main agent default
_DEFAULT_SOUL = (
    "你是一个负责执行子任务的 Agent。"
    "完成任务后直接输出最终结果，不要询问用户。"
)


def _gen_agent_id() -> str:
    return "sa_" + uuid.uuid4().hex[:8]


class SubAgentExecutor:
    """Executes isolated sub-agent tasks spawned via the spawn_agent tool.

    Each spawn_agent call gets a unique agent_id. All spans produced by that
    sub-agent carry agent_id in their attributes, making it easy to filter
    one agent's full context from the shared session trace file.

    State (messages) is stored in _runtime_context["subagent_states"][agent_id]
    so resume_agent can continue from where it left off.
    """

    def __init__(
        self,
        model_client: ModelClient,
        tool_manager: ToolManager,
        tracer: "SessionTracer | None" = None,
    ) -> None:
        self._model = model_client
        self._tools = tool_manager
        self._tracer = tracer

    async def run(
        self,
        task: str,
        tools: str = "",
        system: str = "",
        max_iterations: int = _DEFAULT_MAX_ITERATIONS,
        parent_span: "Span | None" = None,
        agent_id: str | None = None,      # set when resuming an existing agent
    ) -> str:
        """Run (or resume) an isolated sub-agent for the given task.

        Returns the sub-agent's final text response, or a structured
        [AGENT_LIMIT] notice if max_iterations is reached.
        """
        from agentkit.tools.builtin import _runtime_context

        # ── Resolve agent_id and state ──
        is_resume = agent_id is not None
        if not is_resume:
            agent_id = _gen_agent_id()

        states: dict = _runtime_context.setdefault("subagent_states", {})

        if is_resume and agent_id in states:
            # Restore previous messages and tool filter
            state = states[agent_id]
            messages = state["messages"]
            tools = tools or state.get("tools", "")
            system = system or state.get("system", "")
        else:
            # Fresh start
            soul = system.strip() or _DEFAULT_SOUL
            messages = [
                Message(role="system", content=soul),
                Message(role="user", content=task),
            ]

        # ── Filter tool schemas ──
        all_schemas = self._tools.get_tool_schemas()
        if tools:
            allowed = {t.strip() for t in tools.split(",") if t.strip()}
            tool_schemas = [s for s in all_schemas if s["function"]["name"] in allowed]
        else:
            tool_schemas = [s for s in all_schemas if s["function"]["name"] != "spawn_agent"]

        # ── Tracing: subagent span (only for fresh spawns; resumes reuse agent_id tag) ──
        subagent_span: Span | None = None
        if self._tracer and parent_span and not is_resume:
            subagent_span = self._tracer.start_span(
                "subagent",
                parent=parent_span,
                input={"task": task, "tools": tools or "(all)", "agent_id": agent_id},
                attributes={"agent_id": agent_id, "tools_filter": tools},
            )
        elif self._tracer and parent_span and is_resume:
            # For resumes, create a new subagent span tagged with same agent_id
            subagent_span = self._tracer.start_span(
                "subagent",
                parent=parent_span,
                input={"resume": True, "agent_id": agent_id},
                attributes={"agent_id": agent_id, "resume": True},
            )

        # ── Run loop ──
        result = await self._run_loop(
            messages, tool_schemas, subagent_span, max_iterations, agent_id
        )

        # ── Persist state (even on limit, so resume works) ──
        states[agent_id] = {
            "messages": messages,
            "task": task,
            "tools": tools,
            "system": system,
        }

        # ── Close subagent span ──
        if self._tracer and subagent_span:
            self._tracer.end_span(subagent_span, output=result)

        return result

    async def _run_loop(
        self,
        messages: list[Message],
        tool_schemas: list[dict[str, Any]],
        subagent_span: "Span | None",
        max_iterations: int,
        agent_id: str,
    ) -> str:
        for iteration in range(max_iterations):
            # ── sub-turn span ──
            sub_turn: Span | None = None
            if self._tracer and subagent_span:
                user_text = next(
                    (m.content for m in reversed(messages) if m.role == "user"), ""
                )
                sub_turn = self._tracer.start_span(
                    "turn",
                    parent=subagent_span,
                    input=user_text,
                    attributes={"agent_id": agent_id, "sub_agent": True, "iteration": iteration},
                )

            # ── LLM span ──
            llm_span: Span | None = None
            if self._tracer and sub_turn:
                llm_span = self._tracer.start_span(
                    "llm",
                    parent=sub_turn,
                    input={
                        "messages": [m.to_litellm_dict() for m in messages],
                        "model": self._model._config.default,
                    },
                    attributes={"agent_id": agent_id, "model": self._model._config.default},
                )

            resp = await self._model.complete(
                messages=messages,
                tools=tool_schemas if tool_schemas else None,
            )

            if self._tracer and llm_span:
                llm_out: dict[str, Any] = {"content": resp.content}
                if resp.tool_calls:
                    llm_out["tool_calls"] = [
                        {"name": tc.name, "arguments": tc.arguments}
                        for tc in resp.tool_calls
                    ]
                if resp.usage:
                    llm_out["usage"] = {
                        "prompt_tokens": resp.usage.prompt_tokens,
                        "completion_tokens": resp.usage.completion_tokens,
                        "total_tokens": resp.usage.total_tokens,
                        "cache_creation_tokens": resp.usage.cache_creation_tokens,
                        "cache_read_tokens": resp.usage.cache_read_tokens,
                    }
                self._tracer.end_span(llm_span, output=llm_out)

            # ── No tool calls → done ──
            if not resp.tool_calls:
                if self._tracer and sub_turn:
                    self._tracer.end_span(sub_turn, output=resp.content)
                return resp.content or ""

            # ── Execute tool calls ──
            messages.append(Message(
                role="assistant",
                content=resp.content,
                tool_calls=resp.tool_calls,
            ))

            for tc in resp.tool_calls:
                tool_span: Span | None = None
                if self._tracer and sub_turn:
                    tool_span = self._tracer.start_span(
                        "tool",
                        parent=sub_turn,
                        input={"name": tc.name, "arguments": tc.arguments},
                        attributes={"agent_id": agent_id, "tool_name": tc.name},
                    )

                try:
                    result = await self._tools.execute_tool(tc.name, tc.arguments)
                    if self._tracer and tool_span:
                        self._tracer.end_span(tool_span, output={"result": result})
                except Exception as e:
                    result = f"Error: {type(e).__name__}: {e}"
                    if self._tracer and tool_span:
                        self._tracer.end_span(tool_span, output={"error": result}, status="error")

                messages.append(Message(
                    role="tool",
                    content=result,
                    tool_call_id=tc.id,
                    name=tc.name,
                ))

            if self._tracer and sub_turn:
                self._tracer.end_span(sub_turn, output="(tool round complete)")

        # ── Limit reached: return structured notice ──
        last_assistant = next(
            (m.content for m in reversed(messages) if m.role == "assistant" and m.content),
            "(无输出)",
        )
        return (
            f"[AGENT_LIMIT]\n"
            f"agent_id: {agent_id}\n"
            f"已完成: {max_iterations} 轮，任务尚未完成\n"
            f"最后输出: {last_assistant[:300]}\n"
            f"如需继续: resume_agent(agent_id=\"{agent_id}\", max_iterations=20)\n"
            f"如需查看详细执行过程: 读取当前 session 的 trace 文件，过滤 agent_id=\"{agent_id}\" 的 span"
        )
