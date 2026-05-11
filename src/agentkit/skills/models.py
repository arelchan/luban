"""Skill definition model."""

from __future__ import annotations

from pydantic import BaseModel


class SkillDef(BaseModel):
    """A skill definition loaded from a .md file."""

    name: str  # Derived from filename, e.g. "commit" or "ops:deploy"
    description: str = ""
    trigger: str = ""  # e.g. "/commit" or "/ops:deploy"
    prompt_template: str = ""  # Body with $ARGUMENTS placeholder
    source: str = ""  # "builtin" | "user"
