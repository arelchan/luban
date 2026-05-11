"""Session and introspection tools: rename_session, introspect_info, introspect_source."""

from __future__ import annotations

from pathlib import Path

from agentkit.tools.native import tool
from agentkit.tools.builtin.context import _runtime_context


@tool
def rename_session(title: str) -> str:
    """Rename the current session with a descriptive title.

    Use this when the conversation has a clear topic and the default title is unhelpful.
    A good title helps users find past sessions quickly.

    Args:
        title: Short descriptive title for the session, e.g. 'Fix auth bug' or 'Setup CI pipeline'."""
    store = _runtime_context.get("store")
    get_session = _runtime_context.get("get_session")
    set_title = _runtime_context.get("set_title")
    if not store or not get_session or not set_title:
        return "Error: session context not initialized"
    session = get_session()
    set_title(title)
    store.update_meta(session.id, title=title)
    return f"Session renamed to: {title}"


@tool
def introspect_info(category: str = "all") -> str:
    """Get AgentKit runtime information: loaded tools, skills, config, session state, or memory status.

    WHEN TO USE: User asks "what tools do you have", "show config", "session info", or you need to check runtime state.
    WHEN NOT TO USE: You already know the answer from prior context. Don't call every turn.

    Args:
        category: What to inspect. One of: all, tools, skills, commands, config, session, memory."""
    from agentkit import APP_NAME, __version__
    from agentkit.cli.i18n import TEXTS

    sections = []

    if category in ("all", "version"):
        sections.append(f"## Version\n{APP_NAME} v{__version__}")

    if category in ("all", "config"):
        cfg = _runtime_context.get("config")
        if cfg:
            sections.append(
                f"## Config\n"
                f"- Model: {cfg.model.default}\n"
                f"- Temperature: {cfg.model.options.temperature}\n"
                f"- Max tokens: {cfg.model.options.max_tokens}\n"
                f"- Thinking: {cfg.model.options.thinking}\n"
                f"- Context window: {cfg.model.options.context_window}\n"
                f"- Base URL: {cfg.model.base_url or '(default)'}"
            )

    if category in ("all", "tools"):
        tm = _runtime_context.get("tool_manager")
        if tm:
            tools_list = tm.list_tools(lang="en")
            lines = [f"- {t['name']} [{t['source']}]: {t['description']}" for t in tools_list]
            sections.append(f"## Tools ({len(lines)})\n" + "\n".join(lines))

    if category in ("all", "skills"):
        se = _runtime_context.get("skill_executor")
        if se:
            skills = se.list_skills()
            lines = [f"- {s.trigger} ({s.name}) [{s.source}]: {s.description}" for s in skills]
            sections.append(f"## Skills ({len(lines)})\n" + "\n".join(lines))

    if category in ("all", "commands"):
        lang_fn = _runtime_context.get("lang_getter")
        lang = lang_fn() if lang_fn else "zh"
        texts = TEXTS.get(lang, TEXTS["zh"])
        cmd_keys = [k for k in texts if k.startswith("help_") and k not in ("help_title", "help_col_cmd", "help_col_desc")]
        lines = []
        for k in sorted(cmd_keys):
            cmd_name = k.replace("help_", "/").replace("_", " ")
            lines.append(f"- {cmd_name}: {texts[k]}")
        sections.append(f"## Commands ({len(lines)})\n" + "\n".join(lines))

    if category in ("all", "session"):
        get_session = _runtime_context.get("get_session")
        mc = _runtime_context.get("model_client")
        if get_session:
            sess = get_session()
            info = (
                f"## Current Session\n"
                f"- ID: {sess.id}\n"
                f"- Title: {sess.title or '(untitled)'}\n"
                f"- Turn count: {sess.turn_count}\n"
                f"- Model: {sess.model}"
            )
            if mc:
                info += f"\n- Input tokens used: {mc.total_input_tokens}\n- Output tokens used: {mc.total_output_tokens}"
            sections.append(info)

    if category in ("all", "memory"):
        mm = _runtime_context.get("memory_manager")
        if mm:
            lt_status = "enabled" if mm.long_term else "disabled"
            sections.append(
                f"## Memory\n"
                f"- Turns: {mm.short_term.turn_count}\n"
                f"- Messages: {len(mm.short_term.full_log)}\n"
                f"- Long-term: {lt_status}"
            )

    if not sections:
        return f"Unknown category: {category}. Use: all, tools, skills, commands, config, session, memory"
    return "\n\n".join(sections)


@tool
def introspect_source(path: str) -> str:
    """Read AgentKit's own source code or documentation files.

    WHEN TO USE: User asks how AgentKit works internally, or you need to understand AgentKit implementation details.
    WHEN NOT TO USE: Reading user project files → use read_file instead.

    Args:
        path: Relative path within AgentKit source, e.g. 'tools/builtin/files.py', 'README.md', 'config/models.py'."""
    agentkit_src = Path(__file__).parent.parent.parent  # src/agentkit/  (builtin/ → tools/ → agentkit/)
    project_root = agentkit_src.parent.parent           # project root   (agentkit/ → src/ → project/)

    for base in (agentkit_src, project_root):
        target = base / path
        if target.exists() and target.is_file():
            try:
                content = target.read_text(encoding="utf-8")
                if len(content) > 15000:
                    content = content[:15000] + f"\n\n... (truncated, total {len(content)} chars)"
                return content
            except Exception as e:
                return f"Error reading {path}: {e}"

    available = []
    for p in sorted(agentkit_src.rglob("*.py"))[:20]:
        available.append(str(p.relative_to(agentkit_src)))
    for p in sorted(project_root.glob("*.md")):
        available.append(str(p.relative_to(project_root)))

    return (
        f"File not found: {path}\n\n"
        f"Available paths (relative to src/agentkit/ or project root):\n"
        + "\n".join(f"  {a}" for a in available)
    )
