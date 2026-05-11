"""Long-term memory store — persists profile/fact/lesson entries to disk.

Storage format: ~/.agentkit/workspace/memories.json
Each entry has a type (profile/fact/lesson), content, optional vector, and metadata.
"""

from __future__ import annotations

import json
import math
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

MemoryType = Literal["profile", "fact", "lesson"]

_PROFILE_CATEGORIES = ("技术栈", "工作习惯", "沟通偏好", "工作背景")
_FACT_SCOPES = ("project", "environment", "global")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _cosine(a: list[float], b: list[float]) -> float:
    """Cosine similarity between two vectors."""
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    mag_a = math.sqrt(sum(x * x for x in a))
    mag_b = math.sqrt(sum(x * x for x in b))
    if mag_a == 0 or mag_b == 0:
        return 0.0
    return dot / (mag_a * mag_b)


class MemoryStore:
    """Manages structured long-term memory entries.

    Each entry dict shape:
    - profile: {id, type, category, content, evidence, confidence, vector, source_session_id, created_at, updated_at}
    - fact:    {id, type, scope, content, vector, source_session_id, expires_at, created_at, updated_at}
    - lesson:  {id, type, title, content, context, confidence, vector, source_session_id, created_at, updated_at}
    """

    def __init__(self, storage_path: str = "~/.agentkit/workspace/memories.json"):
        self._path = Path(storage_path).expanduser().resolve()
        self._entries: list[dict[str, Any]] = []
        self._load()

    # ── Persistence ──────────────────────────────────────────────────────────

    def _load(self) -> None:
        if self._path.exists():
            try:
                data = json.loads(self._path.read_text(encoding="utf-8"))
                self._entries = data if isinstance(data, list) else []
            except (json.JSONDecodeError, Exception):
                self._entries = []

    def _save(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(
            json.dumps(self._entries, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    # ── CRUD ─────────────────────────────────────────────────────────────────

    def add(self, entry: dict[str, Any]) -> str:
        """Add a new entry. Assigns id and timestamps if missing. Returns id."""
        if "id" not in entry:
            prefix = entry.get("type", "m")[0]
            entry["id"] = f"{prefix}_{uuid.uuid4().hex[:8]}"
        now = _now()
        entry.setdefault("created_at", now)
        entry["updated_at"] = now
        self._entries.append(entry)
        self._save()
        return entry["id"]

    def update(self, entry_id: str, fields: dict[str, Any]) -> bool:
        """Update specific fields of an entry. Returns True if found."""
        for entry in self._entries:
            if entry.get("id") == entry_id:
                fields["updated_at"] = _now()
                entry.update(fields)
                self._save()
                return True
        return False

    def delete(self, entry_id: str) -> bool:
        """Delete an entry by id. Returns True if found."""
        before = len(self._entries)
        self._entries = [e for e in self._entries if e.get("id") != entry_id]
        if len(self._entries) < before:
            self._save()
            return True
        return False

    def get_by_id(self, entry_id: str) -> dict[str, Any] | None:
        for entry in self._entries:
            if entry.get("id") == entry_id:
                return entry
        return None

    def get_all(self, memory_type: MemoryType | None = None) -> list[dict[str, Any]]:
        if memory_type is None:
            return list(self._entries)
        return [e for e in self._entries if e.get("type") == memory_type]

    def count(self) -> dict[str, int]:
        counts: dict[str, int] = {"profile": 0, "fact": 0, "lesson": 0}
        for e in self._entries:
            t = e.get("type", "")
            if t in counts:
                counts[t] += 1
        return counts

    # ── Search ────────────────────────────────────────────────────────────────

    def keyword_search(
        self,
        query: str,
        memory_type: MemoryType | None = None,
        max_results: int = 10,
    ) -> list[dict[str, Any]]:
        """Case-insensitive substring search across content fields."""
        q = query.lower()
        results = []
        pool = self.get_all(memory_type)
        for entry in pool:
            searchable = " ".join(
                str(entry.get(f, ""))
                for f in ("content", "title", "category", "evidence", "context", "scope")
            ).lower()
            if q in searchable:
                results.append(entry)
            if len(results) >= max_results:
                break
        return results

    def vector_search(
        self,
        query_vector: list[float],
        memory_type: MemoryType | None = None,
        top_k: int = 5,
        min_score: float = 0.0,
    ) -> list[tuple[dict[str, Any], float]]:
        """Return top_k entries by cosine similarity. Returns (entry, score) pairs."""
        pool = self.get_all(memory_type)
        scored = []
        for entry in pool:
            vec = entry.get("vector")
            if not vec:
                continue
            score = _cosine(query_vector, vec)
            if score >= min_score:
                scored.append((entry, score))
        scored.sort(key=lambda x: x[1], reverse=True)
        return scored[:top_k]

    def find_similar(
        self,
        vector: list[float],
        memory_type: MemoryType | None = None,
        threshold: float = 0.85,
        top_k: int = 3,
    ) -> list[dict[str, Any]]:
        """Find entries with cosine similarity >= threshold. Used before write to detect duplicates."""
        results = self.vector_search(vector, memory_type, top_k=top_k, min_score=threshold)
        return [entry for entry, _ in results]

    # ── Serialization for LLM injection ──────────────────────────────────────

    def to_context_string(self, memory_type: MemoryType | None = None) -> str:
        """Format memory entries as readable text for system prompt injection."""
        entries = self.get_all(memory_type)
        if not entries:
            return ""

        sections: dict[str, list[str]] = {"profile": [], "fact": [], "lesson": []}
        for e in entries:
            t = e.get("type", "")
            if t == "profile":
                cat = e.get("category", "")
                content = e.get("content", "")
                sections["profile"].append(f"  [{cat}] {content}")
            elif t == "fact":
                scope = e.get("scope", "")
                content = e.get("content", "")
                sections["fact"].append(f"  [{scope}] {content}")
            elif t == "lesson":
                title = e.get("title", "")
                content = e.get("content", "")
                sections["lesson"].append(f"  {title}: {content}")

        lines = []
        if sections["profile"]:
            lines.append("## 用户画像")
            lines.extend(sections["profile"])
        if sections["fact"]:
            lines.append("## 客观事实")
            lines.extend(sections["fact"])
        if sections["lesson"]:
            lines.append("## 经验教训")
            lines.extend(sections["lesson"])

        return "\n".join(lines)
