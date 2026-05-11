"""Task management tools: task_create, task_update, task_get, task_list."""

from __future__ import annotations

from agentkit.tools.native import tool
from agentkit.tools.builtin.context import _runtime_context

_task_store: list[dict] = []
_task_id_counter: list[int] = [0]

_STATUS_ICON = {"pending": "○", "in_progress": "◉", "completed": "✓", "cancelled": "✗", "deleted": "⊘"}
_VALID_STATUSES = {"pending", "in_progress", "completed", "cancelled", "deleted"}


def _render_task_board() -> None:
    renderer = _runtime_context.get("renderer")
    if not renderer:
        return
    active = [t for t in _task_store if t["status"] != "deleted"]
    if not active:
        return
    renderer.show_task_board(active)


@tool
def task_create(title: str, description: str = "", blocked_by: str = "") -> str:
    """Create a task to track a step in a multi-step plan.

    WHEN TO USE: The task has 3+ steps. Create ALL tasks upfront before starting work.
    WHEN NOT TO USE: Single simple task — just do it directly.
    After creating all tasks, call task_list to verify the plan looks right.

    Args:
        title: Brief actionable title in imperative form, e.g. 'Fix auth bug in login flow'.
        description: Detailed description of what needs to be done. Include acceptance criteria.
        blocked_by: Comma-separated task IDs that must complete first, e.g. '1,2'. Empty if no deps."""
    _task_id_counter[0] += 1
    deps = [int(x.strip()) for x in blocked_by.split(",") if x.strip().isdigit()] if blocked_by else []
    task: dict = {
        "id": _task_id_counter[0],
        "title": title,
        "description": description,
        "status": "pending",
        "blocked_by": deps,
        "note": "",
    }
    _task_store.append(task)
    _render_task_board()
    return f"Task #{task['id']} created: {title}"


@tool
def task_update(task_id: int, status: str, note: str = "") -> str:
    """Update a task's status. Mark in_progress BEFORE starting, completed AFTER finishing.

    Only mark completed when FULLY done (tests pass, no errors). If blocked, keep as in_progress.

    Args:
        task_id: The task ID to update.
        status: One of: in_progress, completed, cancelled, deleted.
        note: Optional outcome or reason (shown in task board)."""
    if status not in _VALID_STATUSES:
        return f"Error: status must be one of {sorted(_VALID_STATUSES)}"
    for task in _task_store:
        if task["id"] == task_id:
            task["status"] = status
            if note:
                task["note"] = note
            _render_task_board()
            return f"Task #{task_id} → {status}" + (f": {note}" if note else "")
    return f"Error: Task #{task_id} not found"


@tool
def task_get(task_id: int) -> str:
    """Get full details of a task: description, status, dependencies, and notes.

    Read this before starting a task to understand its full requirements and check if it's still blocked.

    Args:
        task_id: The task ID to retrieve."""
    for task in _task_store:
        if task["id"] == task_id and task["status"] != "deleted":
            blocked_by = task.get("blocked_by", [])
            blocking_open = [
                b for b in blocked_by
                if any(t["id"] == b and t["status"] not in ("completed", "deleted") for t in _task_store)
            ]
            lines = [
                f"Task #{task['id']}: {task['title']}",
                f"Status: {task['status']}",
            ]
            if task.get("description"):
                lines.append(f"Description: {task['description']}")
            if blocked_by:
                lines.append(f"Blocked by: {blocked_by}")
            if blocking_open:
                lines.append(f"⚠ Still blocked by: {blocking_open} — do not start yet")
            if task.get("note"):
                lines.append(f"Note: {task['note']}")
            return "\n".join(lines)
    return f"Error: Task #{task_id} not found"


@tool
def task_list() -> str:
    """List all tasks with status, dependencies, and notes.

    Call after creating tasks to verify the plan, and after completing a task to see what's next."""
    active = [t for t in _task_store if t["status"] != "deleted"]
    if not active:
        return "No tasks."
    lines = []
    for t in active:
        icon = _STATUS_ICON.get(t["status"], "?")
        line = f"[#{t['id']}] {icon} {t['title']} ({t['status']})"
        blocked_by = t.get("blocked_by", [])
        if blocked_by:
            blocking_open = [
                b for b in blocked_by
                if any(bt["id"] == b and bt["status"] not in ("completed", "deleted") for bt in _task_store)
            ]
            if blocking_open:
                line += f" [blocked by #{',#'.join(str(b) for b in blocking_open)}]"
        if t.get("note"):
            line += f" — {t['note']}"
        lines.append(line)
    return "\n".join(lines)
