"""Sub-agent tools: spawn_agent, resume_agent."""

from __future__ import annotations

from agentkit.model.types import Message
from agentkit.tools.native import tool
from agentkit.tools.builtin.context import _runtime_context


@tool
async def spawn_agent(task: str, tools: str = "", system: str = "", max_iterations: int = 20) -> str:
    """Spawn an isolated sub-agent to handle a specific subtask autonomously.

    The sub-agent has its own message history (no shared context with the current conversation).
    Use this to parallelize independent subtasks or delegate specialized work.
    Returns the sub-agent's final response, or a [AGENT_LIMIT] notice with agent_id if limit is reached.

    WHEN TO USE: Complex subtask that needs multiple tool calls, or independent tasks you want to run in parallel.
    WHEN NOT TO USE: Simple one-step operations — just call the tool directly.

    Args:
        task: Natural language description of what the sub-agent should accomplish.
        tools: Comma-separated tool names to allow, e.g. 'web_search,web_fetch'. Empty = all tools except spawn_agent.
        system: Optional system prompt override for the sub-agent's persona/constraints.
        max_iterations: Maximum think-act-observe cycles. Default 20. Increase for complex multi-step tasks."""
    executor = _runtime_context.get("subagent_executor")
    if not executor:
        return "Error: sub-agent executor not initialized"
    parent_span = _runtime_context.get("current_tool_span")
    return await executor.run(
        task=task, tools=tools, system=system,
        max_iterations=max_iterations, parent_span=parent_span,
    )


@tool
async def resume_agent(agent_id: str, instructions: str = "", max_iterations: int = 20) -> str:
    """Resume a sub-agent that previously hit its iteration limit.

    Call this after receiving a [AGENT_LIMIT] notice from spawn_agent.
    The sub-agent continues from exactly where it left off (full message history preserved).
    Returns the sub-agent's final response, or another [AGENT_LIMIT] notice if still not done.

    Args:
        agent_id: The agent_id from the [AGENT_LIMIT] notice.
        instructions: Optional additional guidance to append, e.g. 'focus on X' or 'skip Y and proceed to Z'.
        max_iterations: How many more think-act-observe cycles to allow. Default 20."""
    executor = _runtime_context.get("subagent_executor")
    if not executor:
        return "Error: sub-agent executor not initialized"

    states = _runtime_context.get("subagent_states", {})
    if agent_id not in states:
        return f"Error: agent_id '{agent_id}' not found. It may have expired (session ended) or the ID is incorrect."

    if instructions.strip():
        states[agent_id]["messages"].append(
            Message(role="user", content=instructions.strip())
        )

    parent_span = _runtime_context.get("current_tool_span")
    return await executor.run(
        task=states[agent_id].get("task", ""),
        max_iterations=max_iterations,
        parent_span=parent_span,
        agent_id=agent_id,
    )
