"""Rich-based terminal rendering for Luban CLI."""

from __future__ import annotations

import sys
import threading
import time

from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from agentkit import APP_NAME, __version__
from agentkit.cli.i18n import Lang, t


class _Spinner:
    """A simple inline spinner that runs in a background thread."""

    FRAMES = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]

    def __init__(self):
        self._running = False
        self._thread: threading.Thread | None = None
        self._message = ""

    def start(self, message: str) -> None:
        """Start spinning with a message."""
        self.stop()
        self._message = message
        self._running = True
        self._thread = threading.Thread(target=self._spin, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        """Stop and clear spinner line."""
        if self._running:
            self._running = False
            if self._thread:
                self._thread.join(timeout=0.5)
                self._thread = None
            # Clear the spinner line
            sys.stdout.write("\r\033[K")
            sys.stdout.flush()

    def _spin(self) -> None:
        idx = 0
        while self._running:
            frame = self.FRAMES[idx % len(self.FRAMES)]
            sys.stdout.write(f"\r\033[K\033[2m{frame} {self._message}\033[0m")
            sys.stdout.flush()
            idx += 1
            time.sleep(0.08)


class Renderer:
    """Handles all terminal output via Rich."""

    def __init__(self, console: Console | None = None, lang: Lang = "zh"):
        self.console = console or Console()
        self.lang = lang
        self._streaming = False
        self._stream_buffer = ""       # full content buffer for final render
        self._plain_buffer = ""        # incomplete current line (not yet newline-terminated)
        self._in_code_block = False    # inside ``` ... ```
        self._in_table = False         # inside | ... | rows
        self._rich_buffer = ""         # accumulates code block / table lines for Rich render
        self._spinner = _Spinner()
        self._first_token_received = False
        self._tool_start_time: float = 0.0
        self._pending_tool_args: str = ""

    # ─── Startup ─────────────────────────────────────────────────────────

    def show_banner(self) -> None:
        """Display startup banner with ASCII logo."""
        logo = (
            "[bold blue]"
            "  ██╗     ██╗   ██╗██████╗  █████╗ ███╗   ██╗\n"
            "  ██║     ██║   ██║██╔══██╗██╔══██╗████╗  ██║\n"
            "  ██║     ██║   ██║██████╔╝███████║██╔██╗ ██║\n"
            "  ██║     ██║   ██║██╔══██╗██╔══██║██║╚██╗██║\n"
            "  ███████╗╚██████╔╝██████╔╝██║  ██║██║ ╚████║\n"
            "  ╚══════╝ ╚═════╝ ╚═════╝ ╚═╝  ╚═╝╚═╝  ╚═══╝"
            "[/]"
        )
        self.console.print(logo)
        self.console.print(
            f"  [dim]v{__version__} — {t('banner_hint', self.lang)}[/]\n"
        )

    def show_startup_panel(
        self,
        model: str,
        params: str,
        tools: str,
        session_info: str,
        plugins: str = "",
    ) -> None:
        """Display a compact startup info panel."""
        if self.lang == "zh":
            lines = [
                f"[bold]模型[/]  {model}",
                f"[bold]参数[/]  {params}",
                f"[bold]工具[/]  {tools}",
                f"[bold]会话[/]  {session_info}",
            ]
            if plugins:
                lines.append(f"[bold]插件[/]  {plugins}")
        else:
            lines = [
                f"[bold]Model[/]   {model}",
                f"[bold]Params[/]  {params}",
                f"[bold]Tools[/]   {tools}",
                f"[bold]Session[/] {session_info}",
            ]
            if plugins:
                lines.append(f"[bold]Plugins[/] {plugins}")
        content = "\n".join(lines)
        panel = Panel(
            content,
            title=f"{APP_NAME} v{__version__}",
            title_align="left",
            border_style="blue",
            padding=(0, 1),
        )
        self.console.print(panel)

    # ─── User message ─────────────────────────────────────────────────────

    def show_user_message(self, text: str) -> None:
        """Display user message in conversation (no-op in classic mode, prompt already shows it)."""
        pass

    # ─── System events (unified icon style) ──────────────────────────────

    def show_spinner(self, message: str) -> None:
        """Show a spinner with a message (for long-running operations)."""
        self._spinner.start(message)

    def stop_spinner(self) -> None:
        """Stop the active spinner."""
        self._spinner.stop()

    def show_info(self, message: str) -> None:
        """Display an info message with ℹ icon."""
        if not message:
            self.console.print()
            return
        self.console.print(f"[dim]ℹ {message}[/]")

    def show_success(self, message: str) -> None:
        """Display a success message with ✓ icon."""
        self.console.print(f"[green]✓ {message}[/]")

    def show_warning(self, message: str) -> None:
        """Display a warning message with ⚠ icon."""
        self.console.print(f"[yellow]⚠ {message}[/]")

    def show_error(self, message: str) -> None:
        """Display an error message with ✗ icon."""
        self.console.print(f"[bold red]✗ {message}[/]")

    # ─── Streaming output ────────────────────────────────────────────────

    def start_stream(self) -> None:
        """Begin streaming output."""
        self._streaming = True
        self._stream_buffer = ""
        self._plain_buffer = ""
        self._rich_buffer = ""
        self._in_code_block = False
        self._in_table = False
        self._first_token_received = False
        self.console.print()
        self.console.print(f"[bold blue]◀ {APP_NAME}[/]")
        self._spinner.start(t("status_thinking", self.lang))

    def stream_delta(self, delta: str) -> None:
        """Process a streaming delta.

        Strategy (mirrors Claude Code):
        - Plain text lines → print immediately as they complete (real-time feel)
        - Code blocks (``` ... ```) → buffer entire block, render with Rich when closed
        - Tables (| ... | rows) → buffer entire table, render with Rich when done
        - Incomplete line → hold in _plain_buffer until newline arrives
        """
        if not delta:
            return

        if not self._first_token_received:
            self._first_token_received = True
            self._spinner.stop()

        self._stream_buffer += delta
        self._plain_buffer += delta

        # Process complete lines from the buffer
        while "\n" in self._plain_buffer:
            line, self._plain_buffer = self._plain_buffer.split("\n", 1)
            self._process_stream_line(line)

    def _process_stream_line(self, line: str) -> None:
        """Handle one complete line from the stream."""
        stripped = line.strip()

        # ── Code block toggle ──
        if stripped.startswith("```"):
            if not self._in_code_block:
                self._in_code_block = True
                self._rich_buffer = ""  # discard the ``` fence line
            else:
                self._in_code_block = False
                self._print_code_block(self._rich_buffer)
                self._rich_buffer = ""
            return

        if self._in_code_block:
            self._rich_buffer += line + "\n"
            return

        # ── Table rows ──
        is_table_row = stripped.startswith("|") and stripped.endswith("|")
        if is_table_row:
            if not self._in_table:
                self._in_table = True
                self._rich_buffer = line + "\n"
            else:
                self._rich_buffer += line + "\n"
            return

        if self._in_table:
            self._in_table = False
            self._render_table_lines(self._rich_buffer.splitlines())
            self._rich_buffer = ""

        # ── Plain text / headings / lists → lightweight render ──
        if stripped:
            self.console.print(self._render_inline(line))
        else:
            self.console.print()

    def _print_code_block(self, code: str) -> None:
        """Print a code block with a simple left-border, no background."""
        if not code.strip():
            return
        self.console.print()
        for line in code.rstrip("\n").splitlines():
            self.console.print(f"[dim]│[/] [dim]{line}[/]" if not line.strip() else f"[dim]│[/] {line}")
        self.console.print()

    @staticmethod
    def _render_inline(line: str) -> str:
        """Convert a subset of markdown inline syntax to Rich markup.

        Handles: headings, **bold**, `code`, leading list markers.
        Everything else is passed through as plain text.
        No Markdown() call — avoids dark backgrounds and heavy styling.
        """
        import re as _re

        # Headings: ## Title → bold, no underline
        heading = _re.match(r"^(#{1,6})\s+(.*)", line)
        if heading:
            return f"[bold]{heading.group(2)}[/]"

        # Escape Rich markup characters that aren't ours
        # (only process known patterns, leave rest as-is)
        result = line

        # **bold** or __bold__
        result = _re.sub(r"\*\*(.+?)\*\*", r"[bold]\1[/bold]", result)
        result = _re.sub(r"__(.+?)__", r"[bold]\1[/bold]", result)

        # `inline code` → dim
        result = _re.sub(r"`([^`]+)`", r"[dim]\1[/dim]", result)

        return result

    def end_stream(self) -> None:
        """Flush any remaining buffered content."""
        if not self._streaming:
            return
        self._streaming = False
        self._spinner.stop()

        # Flush incomplete last line (no trailing newline)
        if self._plain_buffer.strip():
            self._process_stream_line(self._plain_buffer)
        self._plain_buffer = ""

        # Flush any open rich buffer (unclosed code block or table)
        if self._rich_buffer:
            if self._in_code_block:
                self._print_code_block(self._rich_buffer)
            elif self._in_table:
                self._render_table_lines(self._rich_buffer.splitlines())
            self._rich_buffer = ""

        self._in_code_block = False
        self._in_table = False
        self._stream_buffer = ""
        self._first_token_received = False
        self.console.print()

    def show_response(self, text: str) -> None:
        """Render assistant response (non-streaming fallback)."""
        self.console.print()
        self.console.print(f"[bold blue]◀ {APP_NAME}[/]")
        self._render_with_tables(text)

    # ─── Task board ──────────────────────────────────────────────────────

    def show_task_board(self, tasks: list[dict]) -> None:
        """Render the current task list as a compact inline board."""
        from agentkit.tools.builtin import _STATUS_ICON
        status_color = {
            "pending": "dim",
            "in_progress": "cyan",
            "completed": "green",
            "cancelled": "dim",
        }
        lines = []
        for t in tasks:
            icon = _STATUS_ICON.get(t["status"], "?")
            color = status_color.get(t["status"], "white")
            blocked_by = t.get("blocked_by", [])
            suffix = ""
            if blocked_by:
                suffix = f" [dim](blocked)[/]"
            lines.append(f"  [{color}]{icon} #{t['id']} {t['title']}[/]{suffix}")
        board = "\n".join(lines)
        self.console.print(f"\n[bold dim]Tasks[/]\n{board}")

    # ─── Tool calls (compact style) ─────────────────────────────────────

    def show_tool_call(self, tool_name: str, arguments: dict) -> None:
        """Record tool call start — defer printing until result arrives."""
        self._spinner.stop()
        # Flush any buffered text that was streamed before tool calls
        # (model may output text + tool_calls in one response)
        if self._plain_buffer.strip():
            self._process_stream_line(self._plain_buffer)
            self._plain_buffer = ""
        if self._rich_buffer:
            if self._in_code_block:
                self._print_code_block(self._rich_buffer)
            elif self._in_table:
                self._render_table_lines(self._rich_buffer.splitlines())
            self._rich_buffer = ""
            self._in_code_block = False
            self._in_table = False
        if self._stream_buffer:
            self._stream_buffer = ""
        self._pending_tool_args = self._format_tool_args(tool_name, arguments)
        self._tool_start_time = time.time()
        exec_msg = t("status_tool_running", self.lang, name=tool_name)
        self._spinner.start(exec_msg)

    def show_tool_result(self, tool_name: str, result: str) -> None:
        """Print a single merged line: ✓/✗ tool_name  args  (duration, summary)."""
        self._spinner.stop()
        elapsed = time.time() - self._tool_start_time if self._tool_start_time else 0
        is_error = result.startswith("Error:") or result.startswith("error:")
        icon = "[red]✗" if is_error else "[green]✓"
        summary = self._summarize_result(tool_name, result)
        args_part = f"  [dim]{self._pending_tool_args}[/]" if self._pending_tool_args else ""
        self.console.print(f"  {icon} {tool_name}[/]{args_part}  [dim]({elapsed:.1f}s, {summary})[/]")
        self._pending_tool_args = ""
        self._spinner.start(t("status_thinking", self.lang))
        self._first_token_received = False

    @staticmethod
    def _summarize_result(tool_name: str, result: str) -> str:
        """Produce a human-readable summary of a tool result.

        Built-in tools get semantic summaries; all others use heuristic fallback.
        """
        # ── Error always wins ──
        if result.startswith("Error:") or result.startswith("error:"):
            # Show first line of error, truncated
            first_line = result.split("\n")[0]
            return first_line[:60] + ("…" if len(first_line) > 60 else "")

        # ── Semantic summaries for known tools ──
        if tool_name == "run_command":
            # Look for exit code marker
            if "[exit code:" in result:
                import re as _re
                m = _re.search(r"\[exit code: (\d+)\]", result)
                code = m.group(1) if m else "?"
                return f"exit {code} ⚠" if code != "0" else f"exit {code}"
            return "exit 0"

        if tool_name == "read_file":
            lines = result.count("\n") + (1 if result and not result.endswith("\n") else 0)
            return f"{lines} lines"

        if tool_name in ("grep_files",):
            # Count actual match lines (exclude separators and truncation notice)
            matches = sum(
                1 for line in result.splitlines()
                if ": " in line and not line.startswith("...")
            )
            return f"{matches} match{'es' if matches != 1 else ''}"

        if tool_name == "glob_files":
            if result == "No files matched the pattern.":
                return "0 files"
            count = len([l for l in result.splitlines() if l.strip()])
            return f"{count} file{'s' if count != 1 else ''}"

        if tool_name == "list_directory":
            count = len([l for l in result.splitlines()[1:] if l.strip()])
            return f"{count} entries"

        if tool_name in ("write_file", "edit_file"):
            return "saved"

        if tool_name == "web_fetch":
            # Try to detect HTTP status from error or content length
            lines = len(result.splitlines())
            return f"{lines} lines"

        if tool_name == "web_search":
            # Each result block is separated by blank lines
            blocks = [b for b in result.split("\n\n") if b.strip()]
            return f"{len(blocks)} result{'s' if len(blocks) != 1 else ''}"

        if tool_name in ("task_create", "task_update", "task_get", "task_list"):
            return "ok"

        if tool_name in ("rename_session",):
            return "ok"

        # ── Heuristic fallback for unknown / MCP tools ──
        lines = result.splitlines()
        line_count = len(lines)
        if line_count > 3:
            return f"{line_count} lines"
        # Single value or short output — show truncated
        brief = result.strip().replace("\n", " ")
        return brief[:50] + ("…" if len(brief) > 50 else "")

    @staticmethod
    def _format_tool_args(tool_name: str, arguments: dict) -> str:
        """Extract the most meaningful argument for compact display."""
        if not arguments:
            return ""
        # Common patterns: show the primary value
        for key in ("path", "file_path", "command", "pattern", "query", "url", "expression", "title"):
            if key in arguments:
                val = str(arguments[key])
                if len(val) > 60:
                    val = val[:57] + "..."
                return val
        # Fallback: show first argument value
        first_val = str(next(iter(arguments.values())))
        if len(first_val) > 60:
            first_val = first_val[:57] + "..."
        return first_val

    # ─── Session history (compact) ───────────────────────────────────────

    def show_session_history(self, messages: list, lang: str | None = None) -> None:
        """Replay recent turns in the same visual style as live conversation."""
        _lang = lang or self.lang

        def _is_real_user_msg(content: str) -> bool:
            """Only real user input has [YYYY-MM-DD HH:MM] prefix."""
            if not content.startswith("["):
                return False
            if "] " not in content[:25]:
                return False
            inner = content[1:content.index("] ")]
            # Must look like a timestamp (e.g. "2025-01-01 12:00"), not "[SYSTEM ...]"
            return len(inner) >= 10 and inner[4:5] == "-"

        # Collect (user_text, assistant_text) pairs
        # Skips system-event user messages (e.g. [SYSTEM ...] plugin notifications)
        turns: list[tuple[str, str]] = []
        i = 0
        while i < len(messages):
            msg = messages[i]
            role = msg.role if hasattr(msg, "role") else msg.get("role", "")
            content = msg.content if hasattr(msg, "content") else msg.get("content", "")
            if role == "user" and content and isinstance(content, str) and _is_real_user_msg(content):
                # Strip timestamp prefix
                user_text = content[content.index("] ") + 2:]
                assistant_text = ""
                j = i + 1
                while j < len(messages):
                    next_msg = messages[j]
                    next_role = next_msg.role if hasattr(next_msg, "role") else next_msg.get("role", "")
                    next_content = next_msg.content if hasattr(next_msg, "content") else next_msg.get("content", "")
                    # Stop at next real user message
                    if next_role == "user" and isinstance(next_content, str) and _is_real_user_msg(next_content):
                        break
                    # Keep updating: take the last non-empty assistant content
                    if next_role == "assistant" and next_content and isinstance(next_content, str):
                        assistant_text = next_content
                    j += 1
                turns.append((user_text, assistant_text))
                i = j  # skip to next user message
                continue
            i += 1

        if not turns:
            return

        # Show last 2 turns; fold the rest with a dim hint
        max_show = 2
        if len(turns) > max_show:
            hidden = len(turns) - max_show
            label = f"  ··· 还有 {hidden} 轮更早的对话 ···" if _lang == "zh" else f"  ··· {hidden} earlier turn{'s' if hidden > 1 else ''} ···"
            self.console.print(f"[dim]{label}[/]\n")
            turns = turns[-max_show:]

        try:
            width = self.console.width - 2
        except Exception:
            width = 78
        if width < 20:
            width = 78

        for user_text, assistant_text in turns:
            # Render user turn — same two-line box as the live input prompt
            top_line = f"\033[2m╭{'─' * width}╮\033[0m"
            import sys as _sys
            _sys.stdout.write(f"{top_line}\n")
            _sys.stdout.flush()
            self.console.print(f"╰─▶ {user_text}")
            # Render assistant turn — same rendering path as live output
            if assistant_text:
                self.console.print()
                self.console.print(f"[bold blue]◀ {APP_NAME}[/]")
                self._render_with_tables(assistant_text)
            self.console.print()


    # ─── Session list ────────────────────────────────────────────────────

    def show_sessions(self, sessions: list, lang: str | None = None) -> None:
        """Display a session selection list."""
        _lang = lang or self.lang
        self.console.print(f"\n[bold]{t('session_list_header', _lang)}[/]")
        for i, sess in enumerate(sessions, 1):
            title = sess.title or "(untitled)"
            self.console.print(
                f"   [cyan]{i})[/] {title}  "
                f"[dim]({sess.turn_count} turns, {sess.updated_at[:10]})[/]"
            )
        self.console.print()

    # ─── Help (grouped) ──────────────────────────────────────────────────

    def show_help(self) -> None:
        """Display available commands grouped by category."""
        if self.lang == "zh":
            groups = [
                ("会话", [
                    ("/sessions", "查看历史会话列表"),
                    ("/session new", "保存当前会话并新建"),
                    ("/title", "查看当前会话标题"),
                    ("/title <name>", "修改会话标题"),
                ]),
                ("上下文", [
                    ("/memory", "查看记忆状态"),
                    ("/compress", "手动压缩上下文"),
                    ("/extract", "触发长期记忆抽取"),
                    ("/clear", "清除对话历史"),
                ]),
                ("工具与技能", [
                    ("/tools", "查看已加载工具"),
                    ("/skills", "查看已加载 Skills"),
                ]),
                ("系统", [
                    ("/models", "查看所有可用模型"),
                    ("/model", "查看当前模型"),
                    ("/model <name>", "切换模型"),
                    ("/usage", "查看当前会话 token 消耗"),
                    ("/log", "打开追踪仪表盘"),
                    ("/lang", "查看当前语言"),
                    ("/lang zh|en", "切换语言"),
                    ("/restart", f"重启 {APP_NAME}"),
                    ("/exit", f"退出 {APP_NAME}"),
                ]),
            ]
        else:
            groups = [
                ("Session", [
                    ("/sessions", "List all sessions"),
                    ("/session new", "Save current and start new"),
                    ("/title", "View current session title"),
                    ("/title <name>", "Rename session title"),
                ]),
                ("Context", [
                    ("/memory", "Show memory status"),
                    ("/compress", "Manually compress context"),
                    ("/extract", "Force long-term memory extraction"),
                    ("/clear", "Clear conversation history"),
                ]),
                ("Tools & Skills", [
                    ("/tools", "List available tools"),
                    ("/skills", "List loaded skills"),
                ]),
                ("System", [
                    ("/models", "List all available models"),
                    ("/model", "View current model"),
                    ("/model <name>", "Switch model"),
                    ("/usage", "Show token usage for this session"),
                    ("/log", "Open tracing dashboard"),
                    ("/lang", "View current language"),
                    ("/lang zh|en", "Switch language"),
                    ("/restart", f"Restart {APP_NAME}"),
                    ("/exit", f"Exit {APP_NAME}"),
                ]),
            ]

        table = Table(
            show_header=False,
            box=None,
            padding=(0, 2, 0, 0),
            show_edge=False,
        )
        table.add_column(style="cyan", no_wrap=True)
        table.add_column()

        for i, (group_name, commands) in enumerate(groups):
            if i > 0:
                table.add_row("", "")  # Spacer between groups
            table.add_row(f"[bold]{group_name}[/]", "")
            for cmd, desc in commands:
                table.add_row(f"  {cmd}", f"[dim]{desc}[/]")

        title = "命令列表" if self.lang == "zh" else "Commands"
        panel = Panel(table, title=title, title_align="left", border_style="dim", padding=(0, 1))
        self.console.print(panel)

    # ─── Table rendering (for streamed markdown tables) ──────────────────

    def _render_with_tables(self, text: str) -> None:
        """Render text that contains markdown tables, using Rich Table for table parts."""
        lines = text.split("\n")
        buffer: list[str] = []
        i = 0
        while i < len(lines):
            if (
                lines[i].strip().startswith("|")
                and lines[i].strip().endswith("|")
                and i + 1 < len(lines)
                and "---" in lines[i + 1]
            ):
                if buffer:
                    for line in buffer:
                        self.console.print(self._render_inline(line) if line.strip() else "")
                    buffer = []
                table_lines = []
                while i < len(lines) and lines[i].strip().startswith("|") and lines[i].strip().endswith("|"):
                    table_lines.append(lines[i])
                    i += 1
                self._render_table_lines(table_lines)
            else:
                buffer.append(lines[i])
                i += 1
        if buffer:
            for line in buffer:
                self.console.print(self._render_inline(line) if line.strip() else "")
        self.console.print()

    def _render_table_lines(self, lines: list[str]) -> None:
        """Parse markdown table lines and render as Rich Table."""
        if len(lines) < 2:
            return

        def split_row(line: str) -> list[str]:
            parts = line.strip().strip("|").split("|")
            return [p.strip() for p in parts]

        headers = split_row(lines[0])
        from rich.box import ROUNDED
        table = Table(show_header=True, header_style="bold", box=ROUNDED, padding=(0, 1))
        for h in headers:
            table.add_column(h)

        for row_line in lines[2:]:
            if set(row_line.replace("|", "").replace("-", "").replace(":", "").strip()) == set():
                continue
            cells = split_row(row_line)
            while len(cells) < len(headers):
                cells.append("")
            table.add_row(*cells[: len(headers)])

        self.console.print(table)


    # ─── Deprecated compatibility ────────────────────────────────────────

    def show_config_loaded(self, config_path: str) -> None:
        """Show config loaded message (kept for compatibility)."""
        pass  # Now handled by show_startup_panel
