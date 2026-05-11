"""Watch context files for changes and trigger re-injection."""

from __future__ import annotations

import asyncio
import time
from pathlib import Path

from watchdog.events import FileModifiedEvent, FileSystemEventHandler
from watchdog.observers import Observer

from agentkit.context.injector import ContextInjector
from agentkit.context.loader import ContextLoader
from agentkit.memory.short_term import ShortTermMemory


class _ContextFileHandler(FileSystemEventHandler):
    """Watchdog handler that detects changes to context files with debouncing."""

    def __init__(
        self,
        watched_files: set[str],
        loop: asyncio.AbstractEventLoop,
        queue: asyncio.Queue[str],
    ):
        self._watched = watched_files
        self._loop = loop
        self._queue = queue
        self._last_event: dict[str, float] = {}
        self._debounce_seconds = 1.0

    def on_modified(self, event: FileModifiedEvent) -> None:  # type: ignore[override]
        if event.is_directory:
            return
        src = str(event.src_path)
        if src in self._watched:
            now = time.time()
            last = self._last_event.get(src, 0)
            if now - last > self._debounce_seconds:
                self._last_event[src] = now
                self._loop.call_soon_threadsafe(self._queue.put_nowait, src)


class ContextWatcher:
    """Watches context files and triggers re-injection on changes."""

    def __init__(
        self,
        loader: ContextLoader,
        injector: ContextInjector,
        memory: ShortTermMemory,
        tools: list[dict] | None = None,
        skills: list | None = None,
        on_reload: callable | None = None,
        memory_store=None,  # agentkit.memory.store.MemoryStore | None — used to re-read profile on reload
    ):
        self._loader = loader
        self._injector = injector
        self._memory = memory
        self._tools = tools
        self._skills = skills
        self._on_reload = on_reload
        self._memory_store = memory_store
        self._observer: Observer | None = None
        self._queue: asyncio.Queue[str] = asyncio.Queue()
        self._consumer_task: asyncio.Task | None = None

    async def start(self) -> None:
        """Start watching context files in a background thread."""
        loop = asyncio.get_running_loop()
        watched_paths = self._loader.get_watched_paths()
        watched_strs = {str(p) for p in watched_paths}

        handler = _ContextFileHandler(
            watched_files=watched_strs,
            loop=loop,
            queue=self._queue,
        )

        self._observer = Observer()
        # Watch the workspace directory
        self._observer.schedule(handler, str(self._loader.workspace), recursive=False)
        self._observer.start()

        # Start async consumer
        self._consumer_task = asyncio.create_task(self._consume_changes())

    async def _consume_changes(self) -> None:
        """Async loop that processes file change events."""
        while True:
            try:
                changed_path = await self._queue.get()
                # Reload all context and re-inject (preserve tool guide + profile)
                context = self._loader.load_all()
                profile_text = self._memory_store.to_context_string("profile") if self._memory_store else None
                self._injector.inject(context, self._memory, tools=self._tools, skills=self._skills, profile_text=profile_text)
                from agentkit.audit import audit as _audit
                from pathlib import Path as _Path
                _audit("context.loader", "context.reload", data={"file": _Path(changed_path).name})
                from agentkit.events import emit_system_event
                emit_system_event(f"配置文件 {_Path(changed_path).name} 已更新并重新加载")
                if self._on_reload:
                    self._on_reload(changed_path)
            except asyncio.CancelledError:
                break
            except Exception:
                pass  # Don't crash the watcher on errors

    async def stop(self) -> None:
        """Stop watching."""
        if self._consumer_task:
            self._consumer_task.cancel()
            try:
                await self._consumer_task
            except asyncio.CancelledError:
                pass
        if self._observer:
            self._observer.stop()
            self._observer.join()
