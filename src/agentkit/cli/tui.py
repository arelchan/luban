"""Terminal UI — prompt_toolkit for input, raw print for output.

Architecture:
- PromptSession with patch_stdout handles input (prompt fixed at bottom)
- During streaming: output goes directly via print (patch_stdout handles it)
- Queue feature: user can type while agent processes, messages queued
- Native scrollback and copy work (no full_screen, no alternate buffer)

Key insight for text selection: avoid writing tiny chunks through patch_stdout.
All streaming output is batched into line-sized prints.
"""

from __future__ import annotations

import asyncio
import sys
from typing import Any, Callable

from prompt_toolkit import PromptSession
from prompt_toolkit.patch_stdout import patch_stdout


class LubanTUI:
    """TUI with fixed input prompt at bottom, scrollable output above.

    Uses prompt_toolkit's patch_stdout to keep prompt fixed while output
    scrolls above it naturally. Text selection and scrollback work natively.
    """

    def __init__(
        self,
        on_submit: Callable[[str], Any] | None = None,
        prompt_text: str = "you> ",
        completer: Any | None = None,
    ):
        self._on_submit = on_submit
        self._prompt_text = prompt_text
        self._completer = completer
        self._running = False
        self._busy = False
        self._queued_texts: list[str] = []
        self._interrupt_event: asyncio.Event = asyncio.Event()
        self._status_text = ""

        # Input queue for async get_input
        self._input_queue: asyncio.Queue[str] = asyncio.Queue()

        # PromptSession (created in run)
        self._session: PromptSession | None = None

        # Streaming buffer — accumulate tokens, flush on newline
        self._stream_buffer = ""

        # Output log (for testing and debugging)
        self._chat_lines: list[str] = []

        # Stream state: "", "thinking", "outputting"
        self._stream_state = ""

    # ─── Public API ───

    def set_busy(self, busy: bool) -> None:
        """Mark whether agent is currently processing."""
        self._busy = busy
        if busy:
            self._interrupt_event.clear()

    @property
    def interrupted(self) -> bool:
        """Check if user pressed Ctrl+C during processing."""
        return self._interrupt_event.is_set()

    def clear_interrupt(self) -> None:
        """Clear the interrupt flag."""
        self._interrupt_event.clear()

    def dequeue_message(self) -> str | None:
        """Pop the first queued message and print it to chat."""
        if not self._queued_texts:
            return None
        text = self._queued_texts.pop(0)
        print(f"▶ you: {text}")
        print()
        self._invalidate_prompt()  # Update queue display
        return text

    def enable_auto_scroll(self) -> None:
        """No-op (terminal always auto-scrolls)."""
        pass

    def set_status(self, text: str) -> None:
        """Update the status text (shown in prompt)."""
        self._status_text = text

    def set_prompt(self, text: str) -> None:
        """Update the prompt text."""
        self._prompt_text = text

    def append_chat(self, text: str) -> None:
        """Print a line to the terminal."""
        self._chat_lines.append(text)
        print(text)

    def append_stream(self, delta: str) -> None:
        """Buffer streaming delta, flush complete lines.

        This avoids rapid tiny writes that cause prompt flickering.
        """
        if self._chat_lines:
            self._chat_lines[-1] += delta
        else:
            self._chat_lines.append(delta)

        # Buffer tokens, flush on newline for smoother output
        self._stream_buffer += delta
        if "\n" in self._stream_buffer:
            lines = self._stream_buffer.split("\n")
            # Print all complete lines
            for line in lines[:-1]:
                print(line)
            # Keep incomplete last part in buffer
            self._stream_buffer = lines[-1]
        elif len(self._stream_buffer) >= 80:
            # Flush if buffer gets long even without newline
            sys.stdout.write(self._stream_buffer)
            sys.stdout.flush()
            self._stream_buffer = ""

    def flush_stream(self) -> None:
        """Flush any remaining stream buffer content."""
        if self._stream_buffer:
            sys.stdout.write(self._stream_buffer)
            sys.stdout.flush()
            self._stream_buffer = ""

    def start_new_line(self) -> None:
        """Start a new line for streaming output."""
        self._chat_lines.append("")
        # Flush buffer and print newline
        self.flush_stream()
        print()

    def set_stream_state(self, state: str) -> None:
        """Set stream state: 'thinking', 'outputting', or '' (clear).

        State is printed as regular output (not embedded in prompt) to avoid
        prompt_toolkit multiline rendering artifacts.
        """
        old_state = self._stream_state
        self._stream_state = state
        # Print state transitions as regular output
        if state == "thinking" and old_state != "thinking":
            print("  ⏳ 思考中...")
        elif state == "outputting" and old_state != "outputting":
            pass  # No need to print — first token output is the signal

    def start_spinner(self, text: str = "思考中") -> None:
        """Show a thinking indicator (legacy compat)."""
        self.set_stream_state("thinking")

    def stop_spinner(self) -> None:
        """Stop the thinking indicator (legacy compat)."""
        self.set_stream_state("")

    async def get_input(self) -> str:
        """Wait for user to submit input. Returns the text."""
        return await self._input_queue.get()

    async def confirm(self, message: str) -> bool:
        """Show a confirmation prompt and wait for y/n response."""
        print(f"⚠ {message} [y/N]")
        self._busy = False
        response = await self._input_queue.get()
        self._busy = True
        return response.lower() in ("y", "yes")

    def _build_prompt(self) -> str:
        """Build prompt: queue above, input line at bottom.

        Example:
          📋 排队中:
          [1] 帮我写个函数
          [2] 然后写测试
        [model | 5k/200k] you> _

        Note: stream state (thinking/outputting) is printed as regular output
        rather than embedded in prompt, to avoid prompt_toolkit multiline
        rendering artifacts when line count changes.
        """
        lines = []
        # Queue display
        if self._queued_texts:
            lines.append("  📋 排队中:\n")
            for i, text in enumerate(self._queued_texts, 1):
                preview = text[:40] + "..." if len(text) > 40 else text
                lines.append(f"  [{i}] {preview}\n")
        # Actual input line (no trailing \n — cursor goes here)
        if self._status_text:
            lines.append(f"[{self._status_text}] {self._prompt_text}")
        else:
            lines.append(self._prompt_text)
        return "".join(lines)

    def _invalidate_prompt(self) -> None:
        """Trigger prompt redraw so dynamic content updates immediately."""
        if self._session and self._session.app and self._session.app.is_running:
            self._session.app.invalidate()

    async def run(self) -> None:
        """Start the input loop (blocks until exit)."""
        self._session = PromptSession(
            completer=self._completer,
            complete_while_typing=True if self._completer else False,
        )
        self._running = True

        with patch_stdout():
            while self._running:
                try:
                    # Use callable prompt so it re-evaluates on each redraw
                    text = await self._session.prompt_async(
                        self._build_prompt,  # callable, not result
                        handle_sigint=False,
                    )
                    text = text.strip()
                    if text:
                        if self._busy:
                            self._queued_texts.append(text)
                            qsize = len(self._queued_texts)
                            print(f"⏳ 已加入队列（前方 {qsize} 条）")
                        else:
                            print(f"▶ you: {text}")
                            print()
                        self._input_queue.put_nowait(text)
                except KeyboardInterrupt:
                    if self._busy:
                        self._interrupt_event.set()
                        print("\n[中断] 已取消当前请求")
                    else:
                        self._input_queue.put_nowait("")
                        break
                except EOFError:
                    self._input_queue.put_nowait("/exit")
                    break

        self._running = False

    def exit(self) -> None:
        """Signal exit."""
        self._running = False

    @property
    def is_running(self) -> bool:
        return self._running

    # ─── Private ───

    def _get_status_text(self) -> str:
        """Get status line content."""
        return self._get_toolbar()

    def _refresh_buffer(self, force: bool = False) -> None:
        """No-op."""
        pass

    def _get_toolbar(self) -> str:
        """Status text content."""
        parts = []
        if self._status_text:
            parts.append(self._status_text)
        if self._queued_texts:
            parts.append(f"排队: {len(self._queued_texts)}")
        if self._busy:
            parts.append("处理中...")
        return " | ".join(parts) if parts else ""
