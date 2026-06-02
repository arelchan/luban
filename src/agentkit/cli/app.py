"""Main CLI entry point for AgentKit."""

from __future__ import annotations

import asyncio
import os
import sys
import webbrowser
from pathlib import Path

from prompt_toolkit.completion import Completer, Completion
from rich.console import Console

from agentkit import APP_NAME
from agentkit.cli.i18n import t
from agentkit.cli.renderer import Renderer
from agentkit.cli.wizard import needs_setup, run_wizard
from agentkit.config.loader import get_config_path, load_config, save_config
from agentkit.context.injector import ContextInjector
from agentkit.context.loader import ContextLoader
from agentkit.context.watcher import ContextWatcher
from agentkit.dashboard.server import DashboardServer
from agentkit.memory.manager import MemoryManager
from agentkit.model.client import ModelClient
from agentkit.model.types import Message
from agentkit.orchestration.loop import AgentLoop
from agentkit.session.store import SessionStore
from agentkit.skills.executor import SkillExecutor
from agentkit.skills.loader import SkillLoader
from agentkit.tools.manager import ToolManager
from agentkit.tracing.collector import SessionTracer

# Import builtin tools so they register themselves
import agentkit.tools.builtin  # noqa: F401




async def _interactive_model_select(
    renderer: Renderer,
    models: list[str],
    current: str,
    lang: str,
) -> str | None:
    """Interactive arrow-key model selector. Returns selected model or None on cancel."""
    import sys
    import tty
    import termios

    # Find current index
    try:
        idx = models.index(current)
    except ValueError:
        idx = 0

    fd = sys.stdin.fileno()
    old_settings = termios.tcgetattr(fd)

    header = "选择模型（↑/↓ 移动，Enter 确认，q 取消）" if lang == "zh" else "Select model (↑/↓ move, Enter confirm, q cancel)"
    current_tag = "(当前)" if lang == "zh" else "(current)"

    # ANSI helpers
    BOLD = "\033[1m"
    GREEN = "\033[32m"
    CYAN = "\033[36m"
    DIM = "\033[2m"
    RESET = "\033[0m"
    CLEAR_LINE = "\033[2K"
    CURSOR_UP = "\033[A"
    HIDE_CURSOR = "\033[?25l"
    SHOW_CURSOR = "\033[?25h"

    def _render_line(i: int, selected_idx: int) -> str:
        m = models[i]
        is_current = m == current
        if i == selected_idx:
            if is_current:
                return f"  {BOLD}{GREEN}❯ {m}{RESET} {DIM}{current_tag}{RESET}"
            else:
                return f"  {BOLD}{CYAN}❯ {m}{RESET}"
        else:
            if is_current:
                return f"    {GREEN}{m}{RESET} {DIM}{current_tag}{RESET}"
            else:
                return f"    {DIM}{m}{RESET}"

    def _draw_all(selected_idx: int) -> None:
        """Draw the full list from scratch."""
        out = ""
        for i in range(len(models)):
            out += CLEAR_LINE + _render_line(i, selected_idx) + "\n"
        # Move back up so cursor sits at the end of the list area
        sys.stdout.write(out)
        sys.stdout.flush()

    def _redraw(selected_idx: int) -> None:
        """Move cursor up over the list, then redraw."""
        sys.stdout.write(CURSOR_UP * len(models))
        _draw_all(selected_idx)

    # Print header with Rich (before entering raw mode)
    renderer.console.print(f"\n[bold]{header}[/]")

    # Initial draw using stdout directly
    sys.stdout.write(HIDE_CURSOR)
    _draw_all(idx)

    try:
        tty.setraw(fd)
        while True:
            ch = sys.stdin.read(1)
            if ch == "\r" or ch == "\n":  # Enter
                break
            elif ch == "q" or ch == "\x03":  # q or Ctrl+C
                idx = -1
                break
            elif ch == "\x1b":  # Escape sequence
                seq = sys.stdin.read(2)
                if seq == "[A":  # Up arrow
                    idx = (idx - 1) % len(models)
                elif seq == "[B":  # Down arrow
                    idx = (idx + 1) % len(models)
                else:
                    continue
                # Redraw in place
                # Temporarily restore terminal to allow proper output
                termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)
                _redraw(idx)
                tty.setraw(fd)
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)
        sys.stdout.write(SHOW_CURSOR)
        sys.stdout.flush()

    renderer.console.print()
    if idx < 0:
        return None
    return models[idx]


async def main() -> None:
    """Main async entry point."""
    import time as _time
    _startup_ts = _time.monotonic()
    console = Console()

    # Load or create config (wizard runs if not configured)
    config_path = get_config_path()
    if needs_setup():
        config = await run_wizard(console)
    else:
        config = load_config(config_path)

    # Boot audit logger and data cleanup
    from agentkit.audit import audit, setup as audit_setup
    from agentkit.cleanup import run_cleanup
    from agentkit import __version__
    audit_setup(config.data.audit_retention_days)
    audit("app", "startup", data={"version": __version__, "model": config.model.default})
    run_cleanup(config.data.trace_retention_days, config.data.session_retention_days)

    # Language from config
    lang = config.cli.language
    renderer = Renderer(console, lang=lang)

    # Initialize model client
    model_client = ModelClient(config.model)

    # Initialize embedder (optional, for long-term memory vectorization)
    from agentkit.model.embedder import Embedder
    embedder = Embedder(config.memory.embedding) if config.memory.embedding.enabled else None

    # Initialize memory manager with compression callbacks
    def _on_compress_start() -> None:
        renderer.show_spinner(t("context_compressing", lang))

    def _on_compress(before_tokens: int, after_tokens: int) -> None:
        renderer.stop_spinner()
        before_k = f"{before_tokens // 1000}k" if before_tokens >= 1000 else str(before_tokens)
        after_k = f"{after_tokens // 1000}k" if after_tokens >= 1000 else str(after_tokens)
        renderer.show_success(t("context_compressed", lang, before=before_k, after=after_k))

    memory_manager = MemoryManager(
        config.memory, model_client,
        on_compress_start=_on_compress_start,
        on_compress=_on_compress,
        embedder=embedder,
    )

    # ─── Session selection ───
    session_store = SessionStore()
    current_session = None

    while current_session is None:
        sessions = session_store.list_sessions()
        if not sessions:
            current_session = session_store.create_session(config.model.default)
            break

        renderer.show_sessions(sessions[:5], lang)
        try:
            choice = (await asyncio.to_thread(input, t("session_prompt", lang))).strip()
        except (EOFError, KeyboardInterrupt):
            # Ctrl+C / Ctrl+D during session selection → exit cleanly
            renderer.show_info(t("goodbye", lang))
            return

        # Delete: d<n>
        if choice.lower().startswith("d") and choice[1:].isdigit():
            n = int(choice[1:])
            visible = sessions[:5]
            if 1 <= n <= len(visible):
                target = visible[n - 1]
                session_store.delete_session(target.id)
                renderer.show_success(t("session_deleted", lang, title=target.title or target.id))
            else:
                renderer.show_warning(t("session_delete_invalid", lang, n=str(n)))
            continue

        # Resume: digit
        if choice.isdigit() and 1 <= int(choice) <= len(sessions[:5]):
            selected = sessions[int(choice) - 1]
            loaded_msgs = session_store.load_session(selected.id)
            memory_manager.add_messages(loaded_msgs)
            current_session = selected
            audit("app", "session.resume", data={"session_id": selected.id, "turn_count": selected.turn_count})
        else:
            # Enter or anything else → new session
            current_session = session_store.create_session(config.model.default)
            audit("app", "session.new", data={"session_id": current_session.id})

    # Initialize tracing with session ID (auto-loads history from trace file)
    tracer = SessionTracer(session_id=current_session.id)
    memory_manager._tracer = tracer

    # Load plugins (scans workspace/plugins/, registers hooks)
    from agentkit.plugins.manager import PluginManager
    _workspace = Path(config.context.workspace_dir).expanduser()
    _plugins_dir = _workspace / config.context.plugins_dir
    plugin_manager = PluginManager(plugins_dir=_plugins_dir)
    plugin_manager.load_all()
    for pid in plugin_manager.loaded_plugins:
        audit("plugin.loader", "plugin.load", data={"plugin_id": pid})
    if plugin_manager.has_plugins:
        tracer.on_span_end = plugin_manager.dispatch_span_end
        # Redirect plugin logging to a file so it never pollutes the terminal.
        # prompt_toolkit owns the terminal; any write to stderr from background
        # threads will corrupt the input box display.
        import logging
        _plugin_log_path = Path("~/.agentkit/plugins.log").expanduser()
        _plugin_handler = logging.FileHandler(_plugin_log_path, encoding="utf-8")
        _plugin_handler.setFormatter(logging.Formatter("%(asctime)s [%(name)s] %(levelname)s: %(message)s"))
        for plugin_id in plugin_manager.loaded_plugins:
            _plogger = logging.getLogger(plugin_id)
            _plogger.setLevel(logging.DEBUG)  # capture all levels including INFO
            _plogger.addHandler(_plugin_handler)
            _plogger.propagate = False  # don't bubble up to root logger → stderr

    # Initialize tool manager first (needed for dynamic tool guide in system prompt)
    tool_manager = ToolManager(config.tools)
    await tool_manager.initialize()
    _tl = tool_manager.list_tools(lang="en")
    audit("tool.manager", "tools.loaded", data={"count": len(_tl), "native": sum(1 for t in _tl if t["source"] == "native"), "mcp": sum(1 for t in _tl if "mcp" in t["source"])})

    # Initialize skills (before context inject so system prompt includes skills directory)
    skill_loader = SkillLoader(user_skills_dir=_workspace / config.context.skills_dir)
    skill_executor = SkillExecutor(skill_loader)
    _skills = skill_executor.list_skills()
    audit("skill.loader", "skills.loaded", data={"count": len(_skills), "skills": [s.trigger for s in _skills]})

    # Initialize context layer — inject tool list + skills directory into system prompt
    context_loader = ContextLoader(config.context)
    context_injector = ContextInjector()
    context = context_loader.load_all()
    tools_list = tool_manager.list_tools(lang="en")  # tool guide always in English (matches docstrings)
    _memory_store = memory_manager.long_term.store if memory_manager.long_term else None
    _profile_text = _memory_store.to_context_string("profile") if _memory_store else None
    context_injector.inject(context, memory_manager.short_term, tools=tools_list, skills=_skills, profile_text=_profile_text, model_name=config.model.default)

    # Start context file watcher (re-injects with tool list + skills on file changes)
    context_watcher: ContextWatcher | None = None
    if config.context.watch_for_changes:
        context_watcher = ContextWatcher(
            loader=context_loader,
            injector=context_injector,
            memory=memory_manager.short_term,
            tools=tools_list,
            skills=_skills,
            on_reload=lambda path: renderer.show_info(f"Context reloaded: {Path(path).name}"),
            memory_store=_memory_store,
            model_name=config.model.default,
        )
        await context_watcher.start()

    # ─── Show startup panel ───
    tools_list_display = tool_manager.list_tools(lang=lang)
    tool_count = len(tools_list_display)
    tool_names_str = ", ".join(item["name"] for item in tools_list_display[:6])
    if tool_count > 6:
        tool_names_str += f" ...({tool_count})"
    else:
        tool_names_str += f" ({tool_count})"

    opts = config.model.options
    params_str = f"temp={opts.temperature} | max={opts.max_tokens} | thinking={'on' if opts.thinking else 'off'} | ctx={opts.context_window // 1000}k"

    if current_session.title:
        session_str = f"{current_session.title} ({current_session.turn_count} turns)" if lang == "en" else f"{current_session.title}（{current_session.turn_count} 轮）"
    else:
        session_str = "New session" if lang == "en" else "新会话"

    plugins_str = ", ".join(plugin_manager.loaded_plugins) if plugin_manager.has_plugins else ""

    audit("app", "startup.complete", data={"session_id": current_session.id},
          duration_ms=(_time.monotonic() - _startup_ts) * 1000)

    # Initialize sub-agent executor
    from agentkit.orchestration.sub_agent import SubAgentExecutor
    subagent_executor = SubAgentExecutor(
        model_client=model_client,
        tool_manager=tool_manager,
        tracer=tracer,
    )

    # Initialize cron scheduler
    from agentkit.cron import Scheduler, JobStore
    cron_store = JobStore()
    cron_store.load_durable()
    cron_scheduler = Scheduler(cron_store)

    # Create dashboard (lazy start on /log)
    dashboard = DashboardServer(tracer)

    # ─── Build slash command completer ───
    _builtin_cmd_descs = [
        ("/help",        "显示帮助" if lang == "zh" else "Show help"),
        ("/tools",       "查看已加载工具" if lang == "zh" else "List tools"),
        ("/skills",      "查看已加载 Skills" if lang == "zh" else "List skills"),
        ("/memory",      "查看记忆状态" if lang == "zh" else "Show memory status"),
        ("/extract",     "手动触发长期记忆抽取" if lang == "zh" else "Extract long-term memory"),
        ("/compress",    "手动压缩上下文" if lang == "zh" else "Compress context"),
        ("/usage",       "查看 token 消耗" if lang == "zh" else "Show token usage"),
        ("/sessions",    "查看历史会话" if lang == "zh" else "List sessions"),
        ("/session new", "新建会话" if lang == "zh" else "New session"),
        ("/title",       "查看/修改会话标题" if lang == "zh" else "View/rename session title"),
        ("/model",       "查看当前模型" if lang == "zh" else "View current model"),
        ("/models",      "查看可用模型" if lang == "zh" else "List available models"),
        ("/log",         "打开 Tracing 仪表盘" if lang == "zh" else "Open tracing dashboard"),
        ("/lang zh",     "切换为中文" if lang == "zh" else "Switch to Chinese"),
        ("/lang en",     "Switch to English"),
        ("/cron",        "定时任务管理" if lang == "zh" else "Cron jobs"),
        ("/clear",       "清除对话历史" if lang == "zh" else "Clear conversation"),
        ("/restart",     f"重启 {APP_NAME}" if lang == "zh" else f"Restart {APP_NAME}"),
        ("/exit",        f"退出 {APP_NAME}" if lang == "zh" else f"Exit {APP_NAME}"),
    ]
    _skill_cmd_descs = [(sk.trigger, sk.description) for sk in skill_executor.list_skills()]
    _all_cmd_descs = _builtin_cmd_descs + _skill_cmd_descs

    class _SlashCompleter(Completer):
        def get_completions(self, document, complete_event):
            text = document.text_before_cursor
            if not text.startswith("/"):
                return
            word = text
            for cmd, desc in _all_cmd_descs:
                if cmd.startswith(word):
                    yield Completion(
                        cmd,
                        start_position=-len(word),
                        display=cmd,
                        display_meta=desc,
                    )

    _slash_completer = _SlashCompleter()

    # ─── Setup TUI ───
    from agentkit.cli.tui import LubanTUI
    from agentkit.cli.tui_renderer import TUIRenderer

    tui = LubanTUI(completer=_slash_completer)
    renderer = TUIRenderer(tui, lang=lang)  # Override Rich renderer with TUI renderer

    # Wire permission confirmation through TUI
    async def _tool_confirm(tool_name: str, arguments: dict) -> bool:
        """Ask user to confirm a tool execution via TUI."""
        import json
        args_preview = json.dumps(arguments, ensure_ascii=False)
        if len(args_preview) > 200:
            args_preview = args_preview[:200] + "..."
        msg = f"执行 `{tool_name}`？\n  参数: {args_preview}" if lang == "zh" else f"Execute `{tool_name}`?\n  Args: {args_preview}"
        return await tui.confirm(msg)

    tool_manager.set_confirm_callback(_tool_confirm)

    # Inject full runtime context for session + introspection + sub-agent tools
    from agentkit.tools.builtin import set_runtime_context
    set_runtime_context(
        session_store=session_store,
        current_session_getter=lambda: current_session,
        current_session_setter=lambda title: setattr(current_session, "title", title),
        tool_manager=tool_manager,
        skill_executor=skill_executor,
        config=config,
        memory_manager=memory_manager,
        model_client=model_client,
        lang_getter=lambda: lang,
        subagent_executor=subagent_executor,
        renderer=renderer,
        tui=tui,
        embedder=embedder,
        scheduler=cron_scheduler,
    )

    # Emit plugin load event (now that memory_manager is available via runtime context)
    if plugin_manager.loaded_plugins:
        from agentkit.events import emit_system_event
        emit_system_event(f"已加载插件：{', '.join(plugin_manager.loaded_plugins)}")

    # Create agent loop
    agent_loop = AgentLoop(
        model_client=model_client,
        tool_manager=tool_manager,
        config=config.orchestration,
        on_stream_delta=renderer.stream_delta,
        on_tool_start=renderer.show_tool_call,
        on_tool_end=renderer.show_tool_result,
        tracer=tracer,
        memory_manager=memory_manager,
    )

    # REPL loop

    async def _extract_memory_silent() -> None:
        """Extract long-term memory silently (no spinner). Used before clear/session new."""
        if memory_manager.long_term and memory_manager.short_term.full_log:
            await memory_manager.extract()

    async def _extract_memory_with_feedback() -> None:
        """Extract long-term memory with spinner and result feedback."""
        if not memory_manager.long_term:
            hint = "长期记忆需要先配置 Embedding 模型，请在 config.toml 的 [memory.embedding] 中配置" if lang == "zh" \
                else "Long-term memory requires Embedding to be configured. Set [memory.embedding] in config.toml"
            renderer.show_warning(hint)
            return
        renderer.show_spinner(t("extracting", lang))
        counts = await memory_manager.extract()
        renderer.stop_spinner()
        if counts and (counts.get("added", 0) + counts.get("updated", 0)) > 0:
            added = counts.get("added", 0)
            updated = counts.get("updated", 0)
            deleted = counts.get("deleted", 0)
            parts = []
            if added:
                parts.append(f"+{added} 条" if lang == "zh" else f"+{added}")
            if updated:
                parts.append(f"更新 {updated} 条" if lang == "zh" else f"updated {updated}")
            if deleted:
                parts.append(f"删除 {deleted} 条" if lang == "zh" else f"deleted {deleted}")
            summary = "，".join(parts) if lang == "zh" else ", ".join(parts)
            renderer.show_success(f"记忆已更新（{summary}）" if lang == "zh" else f"Memory updated ({summary})")
        elif counts is not None:
            renderer.show_info(t("extract_empty", lang))
        else:
            renderer.show_info(t("extract_empty", lang))

    def _check_context_warning() -> None:
        """Show warning if context usage >= 80% after a response."""
        used = memory_manager.short_term.context_tokens
        ctx = config.model.options.context_window
        if ctx > 0:
            ratio = used / ctx
            pct = int(ratio * 100)
            if ratio >= 0.8:
                hint = "/compress 或 /session new" if lang == "zh" else "/compress or /session new"
                renderer.show_warning(f"上下文已达 {pct}%，建议 {hint}" if lang == "zh" else f"Context at {pct}%, consider {hint}")

    async def _cron_poll_loop():
        """Background task that checks and executes due cron jobs."""
        while True:
            await asyncio.sleep(30)
            due_jobs = cron_scheduler.check_due()
            for job in due_jobs:
                await _execute_cron_job(
                    job, cron_scheduler, model_client, tool_manager,
                    config, context, agent_loop, renderer, lang, embedder,
                )

    _cron_task = asyncio.create_task(_cron_poll_loop())

    # Show startup info
    renderer.show_banner()
    renderer.show_startup_panel(
        model=config.model.default,
        params=params_str,
        tools=tool_names_str,
        session_info=session_str,
        plugins=plugins_str,
    )

    # Show session history if resuming
    if hasattr(current_session, 'turn_count') and current_session.turn_count > 0:
        loaded_msgs = memory_manager.short_term.full_log
        if loaded_msgs:
            renderer.show_session_history(loaded_msgs, lang)

    # Update TUI status line with context usage
    def _update_status():
        used = memory_manager.short_term.context_tokens
        ctx = config.model.options.context_window
        used_k = f"{used // 1000}k" if used >= 1000 else str(used)
        ctx_k = f"{ctx // 1000}k" if ctx >= 1000 else str(ctx)
        tui.set_status(f"{config.model.default} | {used_k}/{ctx_k}")

    tui.enable_auto_scroll()

    # Start TUI input loop in background — it collects input via PromptSession
    # while the REPL loop below processes messages from the queue
    _tui_task = asyncio.create_task(tui.run())

    while True:
        _update_status()
        tui.set_busy(False)
        text = await tui.get_input()
        if not text or text == "/exit":
            _cron_task.cancel()
            break
        tui.set_busy(True)
        # If this message was queued (sent during processing), move to chat
        tui.dequeue_message()

        # Handle slash commands
        _cmd_handled = False
        if text.startswith("/"):
            cmd = text.split()[0].lower()
            if cmd in ("/exit", "/quit"):
                break
            elif cmd == "/help":
                renderer.show_help()
                _cmd_handled = True
            elif cmd == "/clear":
                await _extract_memory_silent()
                memory_manager.clear()
                renderer.show_success(t("cleared", lang))
                _cmd_handled = True
            elif cmd == "/tools":
                for item in tool_manager.list_tools(lang=lang):
                    renderer.show_info(
                        f"  [{item['source']}] {item['name']}: {item['description']}"
                    )
                _cmd_handled = True
            elif cmd == "/memory":
                lt = t("memory_enabled", lang) if memory_manager.long_term else t("memory_disabled", lang)
                renderer.show_info(t(
                    "memory_status", lang,
                    turns=str(memory_manager.short_term.turn_count),
                    messages=str(len(memory_manager.short_term.full_log)),
                    long_term=lt,
                ))
                _cmd_handled = True
            elif cmd == "/extract":
                await _extract_memory_with_feedback()
                _cmd_handled = True
            elif cmd == "/models":
                current = config.model.default
                all_models: list[str] = []
                if config.model.providers:
                    for p in config.model.providers:
                        all_models.extend(p.models)
                elif config.model.available:
                    all_models = list(config.model.available)
                if all_models:
                    for i, m in enumerate(all_models, 1):
                        mark = " ◀" if m == current else ""
                        renderer.show_info(f"  {i}) {m}{mark}")
                    hint = "用 /model <名称> 切换" if lang == "zh" else "Use /model <name> to switch"
                    renderer.show_info(hint)
                else:
                    renderer.show_info(f"当前模型：{current}" if lang == "zh" else f"Current model: {current}")
                    hint = "在 config.toml 配置 [[model.providers]] 来管理多供应商模型" if lang == "zh" else "Configure [[model.providers]] in config.toml to manage multi-provider models"
                    renderer.show_info(hint)
                _cmd_handled = True
            elif cmd == "/model":
                parts = text.split(maxsplit=1)
                if len(parts) > 1:
                    new_model = parts[1].strip()
                    found = False
                    if config.model.providers:
                        for p in config.model.providers:
                            if new_model in p.models:
                                found = True
                                break
                    else:
                        found = True
                    if found:
                        old_model = config.model.default
                        config.model.default = new_model
                        renderer.show_success(t("model_switched", lang, model=new_model))
                        from agentkit.events import emit_system_event
                        emit_system_event(f"模型已切换：{old_model} → {new_model}")
                    else:
                        all_models = [m for p in config.model.providers for m in p.models]
                        msg = f"模型 '{new_model}' 未注册。可用：{', '.join(all_models)}" if lang == "zh" else f"Model '{new_model}' not registered. Available: {', '.join(all_models)}"
                        renderer.show_error(msg)
                else:
                    renderer.show_info(t("model_current", lang, model=config.model.default))
                _cmd_handled = True
            elif cmd == "/log":
                if not dashboard.is_running:
                    port = dashboard.start()
                else:
                    port = dashboard.port
                url = f"http://localhost:{port}"
                webbrowser.open(url)
                renderer.show_success(t("dashboard_opened", lang, url=url))
                _cmd_handled = True
            elif cmd == "/lang":
                parts = text.split(maxsplit=1)
                if len(parts) > 1 and parts[1].strip() in ("zh", "en"):
                    lang = parts[1].strip()
                    renderer.lang = lang
                    config.cli.language = lang
                    save_config(config)
                    renderer.show_success(t("lang_switched", lang))
                else:
                    renderer.show_info(t("lang_current", lang))
                _cmd_handled = True
            elif cmd == "/compress":
                log = memory_manager.short_term.full_log
                if len(log) <= 2:
                    renderer.show_info(t("context_no_need", lang))
                else:
                    await memory_manager.compress_if_needed(force=True)
                _cmd_handled = True
            elif cmd == "/usage":
                total_in = model_client.total_input_tokens
                total_out = model_client.total_output_tokens
                cache_creation = model_client.total_cache_creation_tokens
                cache_read = model_client.total_cache_read_tokens
                uncached = total_in - cache_read
                renderer.show_info(t("usage_header", lang))
                renderer.show_info(t("usage_input", lang,
                    total=f"{total_in:,}",
                    cache_read=f"{cache_read:,}",
                    cache_creation=f"{cache_creation:,}",
                    uncached=f"{uncached:,}",
                ))
                renderer.show_info(t("usage_output", lang, output=f"{total_out:,}"))
                renderer.show_info(t("usage_total", lang, all=f"{total_in + total_out:,}"))
                _cmd_handled = True
            elif cmd == "/sessions":
                all_sessions = session_store.list_sessions()
                if all_sessions:
                    renderer.show_sessions(all_sessions[:10], lang)
                else:
                    renderer.show_info(t("session_list_empty", lang))
                _cmd_handled = True
            elif cmd == "/session":
                parts = text.split(maxsplit=1)
                if len(parts) > 1 and parts[1].strip() == "new":
                    await _extract_memory_silent()
                    from datetime import datetime, timezone as tz
                    session_store.save_messages(current_session.id, memory_manager.short_term.full_log)
                    session_store.update_meta(
                        current_session.id,
                        turn_count=memory_manager.short_term.turn_count,
                        updated_at=datetime.now(tz.utc).isoformat(timespec="seconds"),
                    )
                    memory_manager.clear()
                    model_client.total_input_tokens = 0
                    model_client.total_output_tokens = 0
                    current_session = session_store.create_session(config.model.default)
                    renderer.show_info(t("session_created", lang, id=current_session.id))
                else:
                    renderer.show_info(t("session_list_empty", lang))
                _cmd_handled = True
            elif cmd == "/title":
                parts = text.split(maxsplit=1)
                if len(parts) > 1 and parts[1].strip():
                    new_title = parts[1].strip()[:30]
                    current_session.title = new_title
                    session_store.update_meta(current_session.id, title=new_title)
                    renderer.show_success(t("title_updated", lang, title=new_title))
                else:
                    renderer.show_info(t("title_current", lang, title=current_session.title or "(untitled)"))
                _cmd_handled = True
            elif cmd == "/restart":
                renderer.show_info(t("restarting", lang))
                await memory_manager.on_session_end()
                if context_watcher:
                    await context_watcher.stop()
                await tool_manager.shutdown()
                dashboard.stop()
                await model_client.shutdown()
                os.execv(sys.executable, [sys.executable, "-m", "agentkit.cli.app"])
            elif cmd == "/cron":
                await _handle_cron_command(text, cron_scheduler, renderer, lang)
                _cmd_handled = True
            elif cmd == "/skills":
                skills_list = skill_executor.list_skills()
                if skills_list:
                    for sk in skills_list:
                        renderer.show_info(f"  [{sk.source}] {sk.trigger}: {sk.description}")
                else:
                    renderer.show_info("No skills loaded.")
                _cmd_handled = True
            else:
                # Try matching a skill
                skill_match = skill_executor.match(text)
                if skill_match:
                    skill, skill_args = skill_match
                    prompt = skill_executor.build_prompt(skill, skill_args)
                    from datetime import datetime as _dt
                    _ts = _dt.now().strftime("%Y-%m-%d %H:%M")
                    memory_manager.add_message(Message(role="user", content=f"[{_ts}] {prompt}"))
                    try:
                        renderer.start_stream()
                        messages_for_llm = memory_manager.get_messages_for_llm()
                        response_text, new_messages = await agent_loop.run(messages_for_llm)
                        renderer.end_stream()
                        memory_manager.add_messages(new_messages)
                        await memory_manager.on_turn_complete()
                        from datetime import datetime, timezone as tz
                        session_store.save_messages(current_session.id, memory_manager.short_term.full_log)
                        session_store.update_meta(
                            current_session.id,
                            turn_count=memory_manager.short_term.turn_count,
                            updated_at=datetime.now(tz.utc).isoformat(timespec="seconds"),
                        )
                        _check_context_warning()
                    except Exception as e:
                        renderer.end_stream()
                        renderer.show_error(f"{type(e).__name__}: {e}")
                    _cmd_handled = True
        if _cmd_handled:
            continue

        # Add user message to memory (with timestamp for model temporal awareness)
        from datetime import datetime as _dt
        _ts = _dt.now().strftime("%Y-%m-%d %H:%M")

        # Detect media references (images, videos, audio) in user input
        from agentkit.media import detect_media, process_media_refs
        _clean_text, _media_refs = detect_media(text)
        if _media_refs:
            _content_parts = await process_media_refs(_media_refs, _clean_text)
            memory_manager.add_message(Message(role="user", content=_content_parts))
        else:
            memory_manager.add_message(Message(role="user", content=f"[{_ts}] {text}"))

        # Run agent loop with current messages (supports Ctrl+C cancellation)
        try:
            renderer.start_stream()
            messages_for_llm = memory_manager.get_messages_for_llm()

            # Run in a task so we can cancel on Ctrl+C interrupt
            _agent_task = asyncio.create_task(agent_loop.run(messages_for_llm))

            # Wait for either completion or interrupt
            while not _agent_task.done():
                if tui.interrupted:
                    _agent_task.cancel()
                    try:
                        await _agent_task
                    except (asyncio.CancelledError, Exception):
                        pass
                    break
                await asyncio.sleep(0.05)

            renderer.end_stream()

            if tui.interrupted:
                tui.clear_interrupt()
                # Still save partial messages if any were generated
                continue

            response_text, new_messages = _agent_task.result()

            # Add generated messages (assistant + tool results) to memory
            memory_manager.add_messages(new_messages)

            # Check if extraction should trigger
            await memory_manager.on_turn_complete()

            # Auto-save session
            from datetime import datetime, timezone as tz
            session_store.save_messages(current_session.id, memory_manager.short_term.full_log)
            # Generate title via LLM after first turn
            if not current_session.title:
                try:
                    title_prompt = (
                        "请用不超过15个字总结以下对话的主题，只输出标题文字，不要引号和标点：\n"
                        f"用户：{text[:200]}\n"
                        f"助手：{response_text[:200]}"
                    )
                    title_resp = await model_client.complete(
                        [Message(role="user", content=title_prompt)],
                        tools=None,
                    )
                    generated_title = title_resp.content.strip()[:30]
                    current_session.title = generated_title if generated_title else text[:30]
                except Exception:
                    current_session.title = text[:30]
            session_store.update_meta(
                current_session.id,
                title=current_session.title,
                turn_count=memory_manager.short_term.turn_count,
                updated_at=datetime.now(tz.utc).isoformat(timespec="seconds"),
            )
            _check_context_warning()

        except asyncio.CancelledError:
            renderer.end_stream()
        except Exception as e:
            renderer.end_stream()
            renderer.show_error(f"{type(e).__name__}: {e}")

    _cron_task.cancel()
    tui.exit()
    _tui_task.cancel()
    try:
        await _tui_task
    except (asyncio.CancelledError, Exception):
        pass

    # Session end
    await memory_manager.on_session_end()

    if context_watcher:
        await context_watcher.stop()
    await tool_manager.shutdown()
    dashboard.stop()
    plugin_manager.dispatch_session_end(current_session.id)
    audit("app", "shutdown", data={"session_id": current_session.id,
                                    "turns": memory_manager.short_term.turn_count})


async def _handle_cron_command(text: str, scheduler, renderer, lang: str) -> None:
    """Handle /cron subcommands."""
    from datetime import datetime
    from agentkit.cron.job import CronJob
    from agentkit.cron.scheduler import describe_cron, next_fire_time

    parts = text.split(maxsplit=1)
    args = parts[1].strip() if len(parts) > 1 else ""

    if not args or args == "list":
        # /cron list
        jobs = scheduler.store.jobs
        if not jobs:
            renderer.show_info("当前没有活跃的定时任务。" if lang == "zh" else "No active cron jobs.")
            return
        renderer.show_info("ID       频率              过期时间      Prompt")
        for job in jobs:
            desc = describe_cron(job.cron, job.ttl)
            expire_str = datetime.fromtimestamp(job.expires_at).strftime("%m-%d %H:%M") if job.expires_at else "永久"
            durable_mark = " 💾" if job.durable else ""
            renderer.show_info(f"  {job.id}   {desc:<16} {expire_str:<12} {job.prompt[:30]}{durable_mark}")
        return

    if args.startswith("del "):
        # /cron del <id>
        job_id = args[4:].strip()
        removed = scheduler.store.remove(job_id)
        if removed:
            renderer.show_success(f"✓ 已删除任务 {job_id}")
        else:
            renderer.show_error(f"未找到任务 {job_id}")
        return

    if args.startswith("log "):
        # /cron log <id>
        job_id = args[4:].strip()
        job = scheduler.store.get(job_id)
        if not job:
            renderer.show_error(f"未找到任务 {job_id}")
            return
        if not job.messages:
            renderer.show_info(f"任务 {job_id} 尚未执行过。")
            return
        # Show last N message pairs
        for msg in job.messages[-20:]:
            role = msg.get("role", "")
            content = msg.get("content", "")
            if isinstance(content, str) and role in ("user", "assistant"):
                prefix = "→" if role == "user" else "←"
                renderer.show_info(f"  {prefix} {content[:120]}")
        return

    # /cron [--save] [once] "<expr>" <ttl> <prompt>
    durable = False
    if args.startswith("--save "):
        durable = True
        args = args[7:].strip()

    is_once = False
    if args.startswith("once "):
        is_once = True
        args = args[5:].strip()

    # Parse: "cron_expr" ttl prompt  OR  cron_expr ttl prompt
    # Support both quoted and unquoted cron expressions
    if args.startswith('"'):
        # Quoted cron expression
        end_quote = args.index('"', 1)
        cron_expr = args[1:end_quote]
        rest = args[end_quote + 1:].strip()
    else:
        # First token is cron (only works for simple patterns without spaces, or once)
        if is_once:
            cron_expr = "once"
            rest = args
        else:
            # Try to parse 5 fields
            tokens = args.split()
            if len(tokens) < 7:  # 5 cron fields + ttl + at least 1 word prompt
                renderer.show_error('格式：/cron "*/5 * * * *" 1h 任务描述')
                return
            cron_expr = " ".join(tokens[:5])
            rest = " ".join(tokens[5:])

    # rest = "ttl prompt..."
    rest_parts = rest.split(maxsplit=1)
    if len(rest_parts) < 2:
        renderer.show_error('格式：/cron "<频率>" <生命周期> <任务描述>')
        return
    ttl = rest_parts[0]
    prompt = rest_parts[1]

    if is_once:
        cron_expr = "once"

    try:
        job = CronJob.new(cron=cron_expr, ttl=ttl, prompt=prompt, durable=durable)
        scheduler.store.add(job)
    except ValueError as e:
        renderer.show_error(str(e))
        return

    desc = describe_cron(job.cron, job.ttl)
    nxt = next_fire_time(job)
    next_str = datetime.fromtimestamp(nxt).strftime("%H:%M") if nxt else "—"
    expire_str = datetime.fromtimestamp(job.expires_at).strftime("%m-%d %H:%M") if job.expires_at else "永久"
    save_mark = " [已持久化]" if durable else ""

    renderer.show_success(f"✓ [{job.id}] {desc} | {expire_str}过期 | 下次执行：{next_str}{save_mark}")


async def _execute_cron_job(
    job, scheduler, model_client, tool_manager, config, context, agent_loop, renderer, lang, embedder
) -> None:
    """Execute a single cron job in its own context."""
    from datetime import datetime
    from agentkit.cron.scheduler import describe_cron
    from agentkit.memory.manager import MemoryManager
    from agentkit.memory.short_term import ShortTermMemory
    from agentkit.model.types import Message
    from agentkit.context.injector import ContextInjector
    from agentkit.orchestration.loop import AgentLoop

    # Show separator
    ts = datetime.now().strftime("%H:%M")
    renderer.show_info(f"\n───── ⏰ {job.id} | {ts} ─────")

    # Build job-specific memory from its history
    job_memory = MemoryManager(config.memory, model_client)
    for msg_dict in job.messages:
        job_memory.add_message(Message(
            role=msg_dict["role"],
            content=msg_dict.get("content", ""),
            tool_calls=[],
        ))

    # Inject context with cron suffix
    injector = ContextInjector()
    tools_list = tool_manager.list_tools(lang="en")
    injector.inject(context, job_memory.short_term, tools=tools_list)

    # Append cron system suffix to existing system message
    cron_suffix = scheduler.build_cron_system_suffix(job)
    sys_msgs = [m for m in job_memory.short_term.full_log if m.role == "system"]
    if sys_msgs:
        sys_msg = sys_msgs[0]
        sys_msg.content = (sys_msg.content or "") + cron_suffix

    # Add current trigger
    trigger_ts = datetime.now().strftime("%Y-%m-%d %H:%M")
    job_memory.add_message(Message(role="user", content=f"[{trigger_ts}] {job.prompt}"))

    # Build a fresh agent loop for this job
    job_loop = AgentLoop(
        model_client=model_client,
        tool_manager=tool_manager,
        config=config.orchestration,
        on_stream_delta=renderer.stream_delta,
        on_tool_start=renderer.show_tool_call,
        on_tool_end=renderer.show_tool_result,
        memory_manager=job_memory,
    )

    try:
        messages_for_llm = job_memory.get_messages_for_llm()
        renderer.start_stream()
        response_text, new_messages = await job_loop.run(messages_for_llm)
        renderer.end_stream()

        # Save to job history
        job.messages.append({"role": "user", "content": f"[{trigger_ts}] {job.prompt}"})
        if response_text:
            job.messages.append({"role": "assistant", "content": response_text})

        # Trim job history if too long (keep last 40 messages)
        if len(job.messages) > 40:
            job.messages = job.messages[-40:]

    except Exception as e:
        renderer.end_stream()
        renderer.show_error(f"[Cron {job.id}] {type(e).__name__}: {e}")

    # Mark fired
    scheduler.mark_fired(job)
    renderer.show_info("──────────────────────────────\n")


def cli_entry() -> None:
    """Synchronous entry point for pyproject.toml scripts."""
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, EOFError, SystemExit):
        pass
    except asyncio.CancelledError:
        pass
    finally:
        # Ensure clean exit without traceback
        sys.exit(0)


if __name__ == "__main__":
    cli_entry()
