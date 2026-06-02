"""Sub-agent tools: spawn_agent, resume_agent."""

from __future__ import annotations

import asyncio

from agentkit.model.types import Message
from agentkit.tools.native import tool
from agentkit.tools.builtin.context import _runtime_context

# Predefined agent type profiles
_AGENT_TYPES: dict[str, dict[str, str]] = {
    "explore": {
        "tools": "read_file,glob_files,grep_files,list_directory,web_fetch,web_search",
        "system": (
            "你是一个专注于信息收集和代码探索的子代理。"
            "你的任务是搜索、阅读、理解代码或信息，然后汇报发现。"
            "不要修改任何文件，只做探索和分析。"
            "完成后直接输出结果摘要。"
        ),
    },
    "code": {
        "tools": "",  # All tools (except spawn_agent)
        "system": (
            "你是一个专注于代码修改的子代理。"
            "修改文件前必须先 read_file。"
            "完成后直接输出修改摘要和关键变更。"
        ),
    },
    "research": {
        "tools": "web_search,web_fetch,read_file,glob_files,grep_files",
        "system": (
            "你是一个专注于外部信息检索的子代理。"
            "通过搜索引擎和网页抓取收集信息，"
            "整理成结构化的摘要返回。不要修改本地文件。"
        ),
    },
}


@tool
async def spawn_agent(task: str, agent_type: str = "", tools: str = "", system: str = "", max_iterations: int = 20, run_in_background: bool = False) -> str:
    """Spawn an isolated sub-agent to handle a specific subtask autonomously.

    The sub-agent has its own message history (no shared context with the current conversation).
    Use this to parallelize independent subtasks or delegate specialized work.
    Returns the sub-agent's final response, or a [AGENT_LIMIT] notice with agent_id if limit is reached.

    WHEN TO USE: Complex subtask that needs multiple tool calls, or independent tasks you want to run in parallel.
    WHEN NOT TO USE: Simple one-step operations — just call the tool directly.

    Args:
        task: Natural language description of what the sub-agent should accomplish.
        agent_type: Predefined profile — 'explore' (read-only codebase search), 'code' (full tool access), 'research' (web + read). Empty = custom (uses tools/system params).
        tools: Comma-separated tool names to allow, e.g. 'web_search,web_fetch'. Empty = all tools except spawn_agent. Ignored if agent_type is set.
        system: Optional system prompt override for the sub-agent's persona/constraints. Ignored if agent_type is set.
        max_iterations: Maximum think-act-observe cycles. Default 20. Increase for complex multi-step tasks.
        run_in_background: If True, the agent runs in background. Returns immediately with agent_id. The result will be delivered as a system event when complete."""
    executor = _runtime_context.get("subagent_executor")
    if not executor:
        return "Error: sub-agent executor not initialized"

    # Apply agent_type profile (overrides tools/system)
    if agent_type and agent_type in _AGENT_TYPES:
        profile = _AGENT_TYPES[agent_type]
        tools = tools or profile["tools"]
        system = system or profile["system"]
    elif agent_type and agent_type not in _AGENT_TYPES:
        return f"Error: unknown agent_type '{agent_type}'. Available: {', '.join(_AGENT_TYPES.keys())}"

    parent_span = _runtime_context.get("current_tool_span")

    if run_in_background:
        # Run in background — return immediately with agent_id
        from agentkit.orchestration.sub_agent import _gen_agent_id
        agent_id = _gen_agent_id()

        async def _bg_run():
            result = await executor.run(
                task=task, tools=tools, system=system,
                max_iterations=max_iterations, parent_span=parent_span,
                agent_id=agent_id,
            )
            # Notify via system event
            from agentkit.events import emit_system_event
            preview = result[:500] if result else "(无输出)"
            emit_system_event(
                f"[后台Agent完成] agent_id={agent_id}\n任务: {task[:100]}\n结果: {preview}"
            )

        asyncio.create_task(_bg_run())
        return f"[BACKGROUND] agent_id: {agent_id}\n任务已在后台启动。完成后会通过系统事件通知。\n如需查看结果: resume_agent(agent_id=\"{agent_id}\")"

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
