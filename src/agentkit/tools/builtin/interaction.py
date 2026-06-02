"""User interaction tools: ask_user."""

from __future__ import annotations

from agentkit.tools.native import tool
from agentkit.tools.builtin.context import _runtime_context


@tool
async def ask_user(question: str, options: str = "", allow_multiple: bool = False) -> str:
    """Ask the user a structured question and wait for their response.

    Use this when you need user input to proceed — choosing between approaches,
    clarifying requirements, or getting confirmation on non-trivial decisions.
    DO NOT use this for trivial questions you can decide yourself.

    The user always has the option to type a free-form answer instead of selecting an option.

    Args:
        question: Clear, specific question to ask the user. Should end with a question mark.
        options: Pipe-separated options to present, e.g. 'Option A|Option B|Option C'. If empty, user types free-form answer.
        allow_multiple: If True and options are provided, user can select multiple options."""
    renderer = _runtime_context.get("renderer")
    tui = _runtime_context.get("tui")

    if not renderer:
        return "Error: renderer not available"

    # Build the display
    lines = [f"\n❓ {question}"]
    option_list = [o.strip() for o in options.split("|") if o.strip()] if options else []

    if option_list:
        hint = "（可多选，用逗号分隔序号）" if allow_multiple else "（输入序号或直接输入回答）"
        lines.append(hint)
        for i, opt in enumerate(option_list, 1):
            lines.append(f"  [{i}] {opt}")
        lines.append("")

    # Print question
    for line in lines:
        renderer._tui.append_chat(line)

    # Wait for user response via TUI input queue
    if tui:
        response = await tui.get_input()
    else:
        # Fallback: use input()
        import asyncio
        response = await asyncio.to_thread(input, "回答: ")

    response = response.strip()

    # Parse numbered response
    if option_list and response:
        # Check if response is number(s)
        try:
            indices = [int(x.strip()) for x in response.replace("，", ",").split(",")]
            selected = []
            for idx in indices:
                if 1 <= idx <= len(option_list):
                    selected.append(option_list[idx - 1])
            if selected:
                if allow_multiple:
                    return "用户选择: " + ", ".join(selected)
                else:
                    return f"用户选择: {selected[0]}"
        except ValueError:
            pass  # Not a number — treat as free-form

    return f"用户回答: {response}" if response else "用户未回答（空输入）"
