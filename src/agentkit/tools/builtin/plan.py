"""Plan mode tools: enter_plan_mode, exit_plan_mode."""

from __future__ import annotations

from agentkit.tools.native import tool
from agentkit.tools.builtin.context import _runtime_context


@tool
async def enter_plan_mode(goal: str) -> str:
    """Enter plan mode — explore and design an implementation plan before making changes.

    Use this BEFORE starting non-trivial implementation tasks to align with the user.
    In plan mode you should only use read-only tools (read_file, glob_files, grep_files, web_search)
    to understand the codebase, then formulate a step-by-step plan.

    WHEN TO USE:
    - New feature implementation with multiple valid approaches
    - Changes that affect multiple files or existing behavior
    - Architectural decisions (choosing patterns, libraries, strategies)
    - Unclear requirements that need exploration first

    WHEN NOT TO USE:
    - Single-line fixes, typos, obvious bugs
    - User gave very specific, detailed instructions
    - Pure research/exploration tasks

    Args:
        goal: What you're planning to implement. Be specific about the end state."""
    renderer = _runtime_context.get("renderer")
    if renderer:
        renderer._tui.append_chat("")
        renderer._tui.append_chat("━━━ 📋 进入规划模式 ━━━")
        renderer._tui.append_chat(f"  目标: {goal}")
        renderer._tui.append_chat("  规则: 只探索不修改，完成后输出计划让用户审批")
        renderer._tui.append_chat("━━━━━━━━━━━━━━━━━━━━━━━")
        renderer._tui.append_chat("")

    return (
        "[PLAN_MODE_ACTIVE]\n"
        f"目标: {goal}\n\n"
        "你现在处于规划模式。请遵守以下规则：\n"
        "1. 只使用只读工具（read_file, glob_files, grep_files, list_directory, web_search, web_fetch）\n"
        "2. 不要修改任何文件（不要使用 write_file, edit_file, run_command）\n"
        "3. 充分探索后，输出结构化的实现计划\n"
        "4. 计划格式：## 方案概述 → ## 修改文件列表 → ## 实现步骤 → ## 风险点\n"
        "5. 输出计划后，调用 exit_plan_mode 让用户审批\n"
    )


@tool
async def exit_plan_mode(plan_summary: str) -> str:
    """Exit plan mode and present the plan to the user for approval.

    Call this after you've explored the codebase and formulated your implementation plan.
    The user will review and either approve, modify, or reject the plan.

    Args:
        plan_summary: One-line summary of the proposed plan (the full plan should already be in your response text)."""
    renderer = _runtime_context.get("renderer")
    tui = _runtime_context.get("tui")

    if renderer:
        renderer._tui.append_chat("")
        renderer._tui.append_chat("━━━ 📋 规划完成，等待审批 ━━━")
        renderer._tui.append_chat(f"  方案: {plan_summary}")
        renderer._tui.append_chat("━━━━━━━━━━━━━━━━━━━━━━━━━━━")
        renderer._tui.append_chat("")

    # Wait for user approval
    if tui:
        renderer._tui.append_chat("请审批（输入 y 批准执行 / n 放弃 / 或输入修改意见）:")
        response = await tui.get_input()
    else:
        import asyncio
        response = await asyncio.to_thread(input, "审批 (y/n/修改意见): ")

    response = response.strip().lower()

    if response in ("y", "yes", "ok", "好", "批准", "执行"):
        return "[PLAN_APPROVED] 用户已批准计划。请按照计划开始实现。"
    elif response in ("n", "no", "不", "放弃", "取消"):
        return "[PLAN_REJECTED] 用户已拒绝计划。请询问用户想要什么修改。"
    else:
        return f"[PLAN_FEEDBACK] 用户反馈: {response}\n请根据反馈修改计划，然后重新调用 exit_plan_mode。"
