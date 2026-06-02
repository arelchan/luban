"""TUI-aware renderer — outputs to terminal via LubanTUI.

All output goes through tui.append_chat() (print) or tui.append_stream()
(buffered streaming). No ANSI escape codes — pure Unicode text.
"""

from __future__ import annotations

import time

from agentkit import APP_NAME
from agentkit.cli.tui import LubanTUI


class TUIRenderer:
    """Renderer that outputs to terminal through LubanTUI."""

    def __init__(self, tui: LubanTUI, lang: str = "zh"):
        self.lang = lang
        self._tui = tui
        self._streaming = False
        self._got_first_token = False
        self._tool_start_time: float = 0.0
        self._pending_tool_name: str = ""
        self._pending_tool_args: str = ""

    # ─── Startup ─────────────────────────────────────────────────────────

    def show_banner(self) -> None:
        from agentkit import __version__
        self._tui.append_chat("")
        self._tui.append_chat("  ██╗     ██╗   ██╗██████╗  █████╗ ███╗   ██╗")
        self._tui.append_chat("  ██║     ██║   ██║██╔══██╗██╔══██╗████╗  ██║")
        self._tui.append_chat("  ██║     ██║   ██║██████╔╝███████║██╔██╗ ██║")
        self._tui.append_chat("  ██║     ██║   ██║██╔══██╗██╔══██║██║╚██╗██║")
        self._tui.append_chat("  ███████╗╚██████╔╝██████╔╝██║  ██║██║ ╚████║")
        self._tui.append_chat("  ╚══════╝ ╚═════╝ ╚═════╝ ╚═╝  ╚═╝╚═╝  ╚═══╝")
        self._tui.append_chat(f"  v{__version__}")
        self._tui.append_chat("")

    def show_startup_panel(self, model: str, params: str, tools: str, session_info: str, plugins: str = "") -> None:
        from agentkit import __version__
        self._tui.append_chat(f"  ┌─ {APP_NAME} v{__version__} ─────────────────────────────────┐")
        self._tui.append_chat(f"  │ 模型  {model}")
        self._tui.append_chat(f"  │ 参数  {params}")
        self._tui.append_chat(f"  │ 工具  {tools}")
        self._tui.append_chat(f"  │ 会话  {session_info}")
        if plugins:
            self._tui.append_chat(f"  │ 插件  {plugins}")
        self._tui.append_chat("  └──────────────────────────────────────────────┘")
        self._tui.append_chat("")

    # ─── User message ─────────────────────────────────────────────────────

    def show_user_message(self, text: str) -> None:
        self._tui.append_chat("")
        self._tui.append_chat(f"▶ you: {text}")
        self._tui.append_chat("")

    # ─── Messages ────────────────────────────────────────────────────────

    def show_info(self, message: str) -> None:
        if not message:
            self._tui.append_chat("")
            return
        self._tui.append_chat(f"  ℹ {message}")

    def show_success(self, message: str) -> None:
        self._tui.append_chat(f"  ✓ {message}")

    def show_warning(self, message: str) -> None:
        self._tui.append_chat(f"  ⚠ {message}")

    def show_error(self, message: str) -> None:
        self._tui.append_chat(f"  ✗ {message}")

    # ─── Spinner ──────────────────────────────────────────────────────────

    def show_spinner(self, message: str) -> None:
        self._tui.start_spinner(message)

    def stop_spinner(self) -> None:
        self._tui.stop_spinner()

    # ─── Streaming ─────────────────────────────────────────────────────

    def start_stream(self) -> None:
        """Begin a streaming response. Shows thinking state."""
        self._streaming = True
        self._got_first_token = False
        self._tui.append_chat("")
        self._tui.set_stream_state("thinking")  # ⏳ 思考中...

    def stream_delta(self, token: str) -> None:
        """Stream token (buffered, flushes on newline or 80 chars)."""
        if not self._streaming or not token:
            return
        # First token: transition thinking → outputting
        if not self._got_first_token:
            self._got_first_token = True
            self._tui.set_stream_state("outputting")  # ✍ 输出中...
            self._tui.append_chat(f"◀ {APP_NAME}")
            self._tui.start_new_line()
        self._tui.append_stream(token)

    def stream_token(self, token: str) -> None:
        """Alias for stream_delta."""
        self.stream_delta(token)

    def end_stream(self) -> None:
        """End streaming — flush buffer, clear state."""
        if not self._streaming:
            return
        self._streaming = False
        self._tui.set_stream_state("")  # Clear state indicator
        self._tui.flush_stream()
        self._tui.append_chat("")

    # ─── Tool calls ────────────────────────────────────────────────────────

    def show_tool_call(self, tool_name: str, arguments: dict) -> None:
        """Show tool execution start."""
        args_preview = ""
        if arguments:
            if len(arguments) == 1:
                args_preview = str(list(arguments.values())[0])[:60]
            else:
                args_preview = ", ".join(f"{k}={v}" for k, v in list(arguments.items())[:2])[:60]
        self._pending_tool_name = tool_name
        self._pending_tool_args = args_preview
        self._tool_start_time = time.time()
        args_str = f"  {args_preview}" if args_preview else ""
        self._tui.append_chat(f"  ⏳ {tool_name}{args_str}")

    def show_tool_result(self, tool_name: str, result: str) -> None:
        """Show tool execution result."""
        elapsed = time.time() - self._tool_start_time if self._tool_start_time else 0
        elapsed_str = f" {elapsed:.1f}s" if elapsed else ""
        result_preview = result[:60].replace("\n", " ") if result else ""
        is_error = result_preview.startswith("Error:") if result_preview else False
        icon = "✗" if is_error else "✓"
        summary = f"  ({result_preview}{elapsed_str})" if result_preview else ""
        self._tui.append_chat(f"  {icon} {tool_name}{summary}")
        self._tool_start_time = 0.0

    # Legacy aliases
    def show_tool_start(self, name: str, args_preview: str = "") -> None:
        self.show_tool_call(name, {"args": args_preview} if args_preview else {})

    def show_tool_end(self, name: str, result_preview: str = "", elapsed: float = 0) -> None:
        self.show_tool_result(name, result_preview)

    # ─── Sessions ────────────────────────────────────────────────────────

    def show_sessions(self, sessions: list, lang: str = "zh") -> None:
        self._tui.append_chat("  会话列表:" if lang == "zh" else "  Sessions:")
        for i, s in enumerate(sessions[:10], 1):
            title = getattr(s, "title", None) or (s.get("title", "(untitled)") if isinstance(s, dict) else "(untitled)")
            turns = getattr(s, "turn_count", 0) if not isinstance(s, dict) else s.get("turn_count", 0)
            self._tui.append_chat(f"    {i}) {title}  ({turns} turns)")

    # ─── Session history ─────────────────────────────────────────────────

    def show_session_history(self, messages: list, lang: str = "zh") -> None:
        """Render conversation history."""
        turns: list[tuple[str, str, list[str]]] = []
        i = 0
        while i < len(messages):
            msg = messages[i]
            role = getattr(msg, "role", None) or (msg.get("role", "") if isinstance(msg, dict) else "")
            content = getattr(msg, "content", None) or (msg.get("content", "") if isinstance(msg, dict) else "")
            if role == "user" and content and isinstance(content, str) and self._is_real_user_message(content):
                user_text = content[content.index("] ") + 2:]
                assistant_text = ""
                tool_names: list[str] = []
                j = i + 1
                while j < len(messages):
                    next_msg = messages[j]
                    next_role = getattr(next_msg, "role", None) or (next_msg.get("role", "") if isinstance(next_msg, dict) else "")
                    next_content = getattr(next_msg, "content", None) or (next_msg.get("content", "") if isinstance(next_msg, dict) else "")
                    if next_role == "user" and isinstance(next_content, str) and self._is_real_user_message(next_content):
                        break
                    if next_role == "assistant":
                        tool_calls = getattr(next_msg, "tool_calls", None)
                        if tool_calls is None and isinstance(next_msg, dict):
                            tool_calls = next_msg.get("tool_calls")
                        if tool_calls:
                            for tc in tool_calls:
                                name = getattr(tc, "name", None) or (tc.get("name", "") if isinstance(tc, dict) else "")
                                if name:
                                    tool_names.append(name)
                        if next_content and isinstance(next_content, str):
                            assistant_text = next_content
                    j += 1
                turns.append((user_text, assistant_text, tool_names))
                i = j
                continue
            i += 1

        if not turns:
            return

        self._tui.append_chat(f"  ─── 会话历史（{len(turns)} 轮）───" if lang == "zh" else f"  ─── History ({len(turns)} turns) ───")
        self._tui.append_chat("")

        for user_text, assistant_text, tool_names in turns:
            self._tui.append_chat(f"▶ you: {user_text}")
            if tool_names:
                for tn in tool_names:
                    self._tui.append_chat(f"  ✓ {tn}")
            if assistant_text:
                self._tui.append_chat(f"◀ {APP_NAME}:")
                preview = assistant_text[:500]
                for line in preview.split("\n"):
                    self._tui.append_chat(f"  {line}")
                if len(assistant_text) > 500:
                    self._tui.append_chat("  ...")
            self._tui.append_chat("")

    def _is_real_user_message(self, content: str) -> bool:
        if content.startswith("[") and "] " in content[:25]:
            bracket_end = content.index("] ")
            inner = content[1:bracket_end]
            if len(inner) >= 10 and inner[4] == "-":
                return True
        return False

    # ─── Help ────────────────────────────────────────────────────────────

    def show_help(self) -> None:
        self._tui.append_chat("┌─ 命令列表 ─────────────────────────────┐")
        self._tui.append_chat("│ /sessions     查看历史会话              │")
        self._tui.append_chat("│ /session new  保存当前并新建            │")
        self._tui.append_chat("│ /title        查看/修改会话标题         │")
        self._tui.append_chat("│ /memory       查看记忆状态              │")
        self._tui.append_chat("│ /compress     手动压缩上下文            │")
        self._tui.append_chat("│ /extract      触发长期记忆抽取          │")
        self._tui.append_chat("│ /tools        查看已加载工具            │")
        self._tui.append_chat("│ /skills       查看已加载 Skills         │")
        self._tui.append_chat("│ /models       查看所有可用模型          │")
        self._tui.append_chat("│ /model <name> 切换模型                  │")
        self._tui.append_chat("│ /usage        查看 token 消耗           │")
        self._tui.append_chat("│ /cron         定时任务管理              │")
        self._tui.append_chat("│ /log          打开追踪仪表盘            │")
        self._tui.append_chat("│ /lang zh|en   切换语言                  │")
        self._tui.append_chat("│ /clear        清除对话历史              │")
        self._tui.append_chat("│ /exit         退出                      │")
        self._tui.append_chat("└─────────────────────────────────────────┘")
