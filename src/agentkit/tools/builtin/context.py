"""Runtime context bridge — dependency injection for tool functions.

All tool modules import _runtime_context from here.
cli/app.py calls set_runtime_context() after initialization.
"""

from __future__ import annotations

# Runtime bridge: set by cli/app.py after initialization
_runtime_context: dict = {}

# Keep backward compat alias
_session_context = _runtime_context


def set_runtime_context(
    session_store=None,
    current_session_getter=None,
    current_session_setter=None,
    tool_manager=None,
    skill_executor=None,
    config=None,
    memory_manager=None,
    model_client=None,
    lang_getter=None,
    subagent_executor=None,
    renderer=None,
    tui=None,
    embedder=None,
    scheduler=None,
) -> None:
    """Inject runtime state for session and introspection tools.

    Called by cli/app.py after all components are initialized.
    """
    if session_store is not None:
        _runtime_context["store"] = session_store
    if current_session_getter is not None:
        _runtime_context["get_session"] = current_session_getter
    if current_session_setter is not None:
        _runtime_context["set_title"] = current_session_setter
    if tool_manager is not None:
        _runtime_context["tool_manager"] = tool_manager
    if skill_executor is not None:
        _runtime_context["skill_executor"] = skill_executor
    if config is not None:
        _runtime_context["config"] = config
    if memory_manager is not None:
        _runtime_context["memory_manager"] = memory_manager
    if model_client is not None:
        _runtime_context["model_client"] = model_client
    if lang_getter is not None:
        _runtime_context["lang_getter"] = lang_getter
    if subagent_executor is not None:
        _runtime_context["subagent_executor"] = subagent_executor
    if renderer is not None:
        _runtime_context["renderer"] = renderer
    if tui is not None:
        _runtime_context["tui"] = tui
    if embedder is not None:
        _runtime_context["embedder"] = embedder
    if scheduler is not None:
        _runtime_context["scheduler"] = scheduler


def set_session_context(session_store, current_session_getter, current_session_setter) -> None:
    """Legacy wrapper — use set_runtime_context instead."""
    set_runtime_context(
        session_store=session_store,
        current_session_getter=current_session_getter,
        current_session_setter=current_session_setter,
    )
