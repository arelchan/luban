"""Session data models."""

from __future__ import annotations

from pydantic import BaseModel, Field


class SessionMeta(BaseModel):
    """Metadata for a single session (stored in index.json)."""

    id: str
    title: str = ""
    created_at: str = ""  # ISO format
    updated_at: str = ""  # ISO format
    turn_count: int = 0
    model: str = ""


class SessionData(BaseModel):
    """Full session data (stored per-session file)."""

    id: str
    messages: list[dict] = Field(default_factory=list)
