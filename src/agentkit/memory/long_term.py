"""Long-term memory: extracts and persists structured knowledge from conversation logs.

Three memory types:
- profile: user traits, preferences, background
- fact: objective project/environment facts
- lesson: reusable rules and hard-won experience

Write path:
  conversation log → LLM extraction → operations JSON → MemoryStore
  Before each write, vector-search for similar entries → LLM decides update/merge/add/skip

Read path (called by tools):
  query → MemoryStore.keyword_search / vector_search / get_all(profile)
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from agentkit.config.models import LongTermMemoryConfig
from agentkit.memory.prompts import DEFAULT_EXTRACTION_PROMPT
from agentkit.memory.store import MemoryStore
from agentkit.model.client import ModelClient
from agentkit.model.types import Message


class LongTermMemory:
    """Coordinates long-term memory extraction and retrieval."""

    def __init__(
        self,
        config: LongTermMemoryConfig,
        model_client: ModelClient,
        embedder=None,  # agentkit.model.embedder.Embedder | None
    ):
        self._config = config
        self._model = model_client
        self._embedder = embedder
        self._store = MemoryStore(config.memories_file)
        # Keep legacy memory.md path for backward compat
        self._legacy_path = Path(config.storage_file).expanduser()
        self._extraction_prompt = config.extraction_prompt or DEFAULT_EXTRACTION_PROMPT

    @property
    def store(self) -> MemoryStore:
        return self._store

    # ── Extraction (write path) ───────────────────────────────────────────────

    async def extract_and_update(self, conversation_log: list[Message]) -> dict[str, int]:
        """Extract memories from conversation log and update the store.

        Returns dict with counts: {added, updated, deleted, skipped}
        """
        if not conversation_log:
            return {"added": 0, "updated": 0, "deleted": 0, "skipped": 0}

        conv_text = self._format_conversation(conversation_log)
        existing_text = self._format_existing_memories()

        prompt = self._extraction_prompt.format(
            existing_memories=existing_text or "(暂无已有记忆)",
            conversation_log=conv_text,
        )

        # Use extraction_model if explicitly set; otherwise fall back to the main model
        extraction_model = self._config.extraction_model or None
        response = await self._model.complete(
            messages=[Message(role="user", content=prompt)],
            model=extraction_model,
        )

        operations = self._parse_operations(response.content or "")
        if not operations:
            return {"added": 0, "updated": 0, "deleted": 0, "skipped": 0}

        return await self._apply_operations(operations)

    def _parse_operations(self, raw: str) -> list[dict[str, Any]]:
        """Parse LLM response into operations list. Tolerates code block wrapping."""
        # Strip ```json ... ``` wrapper if present
        text = raw.strip()
        match = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
        if match:
            text = match.group(1).strip()

        try:
            data = json.loads(text)
            ops = data.get("operations", [])
            return ops if isinstance(ops, list) else []
        except (json.JSONDecodeError, Exception):
            return []

    async def _apply_operations(self, operations: list[dict[str, Any]]) -> dict[str, int]:
        """Apply operations to the MemoryStore. Returns change counts."""
        counts = {"added": 0, "updated": 0, "deleted": 0, "skipped": 0}

        for op in operations:
            action = op.get("action", "")
            try:
                if action == "add":
                    await self._do_add(op)
                    counts["added"] += 1
                elif action in ("update", "merge"):
                    target_id = op.get("target_id")
                    if target_id:
                        fields: dict[str, Any] = {}
                        if "content" in op:
                            fields["content"] = op["content"]
                        if action == "merge" and "context" in op:
                            fields["context"] = op["context"]
                        if fields:
                            self._store.update(target_id, fields)
                            counts["updated"] += 1
                elif action == "delete":
                    target_id = op.get("target_id")
                    if target_id and self._store.delete(target_id):
                        counts["deleted"] += 1
                elif action == "skip":
                    counts["skipped"] += 1
            except Exception:
                counts["skipped"] += 1

        return counts

    async def _do_add(self, op: dict[str, Any]) -> None:
        """Build and persist a new memory entry, with optional embedding."""
        mem_type = op.get("type", "")
        if mem_type not in ("profile", "fact", "lesson"):
            return

        # Resolve current session id for traceability
        try:
            from agentkit.tools.builtin import _runtime_context as _rtc
            _get_session = _rtc.get("get_session")
            source_session_id = _get_session().id if _get_session else ""
        except Exception:
            source_session_id = ""

        entry: dict[str, Any] = {"type": mem_type, "source_session_id": source_session_id}

        if mem_type == "profile":
            entry["category"] = op.get("category", "")
            entry["content"] = op.get("content", "")
            entry["evidence"] = op.get("evidence", "")
            entry["confidence"] = 0.7
        elif mem_type == "fact":
            entry["scope"] = op.get("scope", "global")
            entry["content"] = op.get("content", "")
            entry["expires_at"] = None
        elif mem_type == "lesson":
            entry["title"] = op.get("title", "")
            entry["content"] = op.get("content", "")
            entry["context"] = op.get("context", "")
            entry["confidence"] = 0.7

        # Generate embedding if available
        content_for_embed = entry.get("content", "")
        if self._embedder and self._embedder.enabled and content_for_embed:
            vec = await self._embedder.embed(content_for_embed)
            if vec:
                entry["vector"] = vec

        self._store.add(entry)

    # ── Formatting helpers ────────────────────────────────────────────────────

    def _format_conversation(self, messages: list[Message]) -> str:
        lines = []
        for msg in messages:
            if msg.role == "system":
                continue
            prefix = {"user": "用户", "assistant": "助手", "tool": "工具"}.get(msg.role, msg.role)
            if msg.role == "tool" and msg.name:
                prefix = f"工具({msg.name})"
            content = msg.content or ""
            if len(content) > 800:
                content = content[:800] + "..."
            lines.append(f"{prefix}: {content}")
        return "\n".join(lines)

    def _format_existing_memories(self) -> str:
        """Format existing entries as compact JSON list for the extraction prompt."""
        entries = self._store.get_all()
        if not entries:
            return ""
        # Strip vectors to save tokens
        compact = []
        for e in entries:
            item = {k: v for k, v in e.items() if k not in ("vector",)}
            compact.append(item)
        return json.dumps(compact, ensure_ascii=False, indent=2)

    # ── Legacy compat ─────────────────────────────────────────────────────────

    def load_existing(self) -> str:
        """Legacy: return memory as plain text (for backward compat)."""
        return self._store.to_context_string()
