"""CronJob data model."""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Any


@dataclass
class CronJob:
    """A scheduled task."""

    id: str
    cron: str                          # "*/5 * * * *" or "once"
    ttl: str                           # "1h", "7d", "forever"
    prompt: str                        # Prompt to inject when triggered
    created_at: float = field(default_factory=time.time)
    expires_at: float | None = None    # None = forever
    last_fired: float = 0.0
    durable: bool = False
    messages: list[dict[str, Any]] = field(default_factory=list)  # Job's own conversation history

    @staticmethod
    def new(cron: str, ttl: str, prompt: str, durable: bool = False) -> CronJob:
        """Create a new CronJob with auto-generated ID and computed expiry."""
        job_id = uuid.uuid4().hex[:6]
        created = time.time()
        expires = _parse_ttl(ttl, created)
        return CronJob(
            id=job_id,
            cron=cron,
            ttl=ttl,
            prompt=prompt,
            created_at=created,
            expires_at=expires,
            durable=durable,
        )

    @property
    def is_once(self) -> bool:
        return self.cron == "once"

    @property
    def is_expired(self) -> bool:
        """Check if job has expired.

        For once jobs: expired means it has already fired (expires_at is the fire time).
        For recurring jobs: expired means current time > expires_at.
        """
        if self.expires_at is None:
            return False
        if self.is_once:
            # Once jobs "expire" only after they've fired
            return self.last_fired > 0
        return time.time() >= self.expires_at

    def to_dict(self) -> dict[str, Any]:
        """Serialize for JSON persistence."""
        return {
            "id": self.id,
            "cron": self.cron,
            "ttl": self.ttl,
            "prompt": self.prompt,
            "created_at": self.created_at,
            "expires_at": self.expires_at,
            "last_fired": self.last_fired,
            "durable": self.durable,
            "messages": self.messages,
        }

    @staticmethod
    def from_dict(data: dict[str, Any]) -> CronJob:
        """Deserialize from JSON."""
        return CronJob(
            id=data["id"],
            cron=data["cron"],
            ttl=data["ttl"],
            prompt=data["prompt"],
            created_at=data.get("created_at", 0),
            expires_at=data.get("expires_at"),
            last_fired=data.get("last_fired", 0),
            durable=data.get("durable", False),
            messages=data.get("messages", []),
        )


def _parse_ttl(ttl: str, base_time: float) -> float | None:
    """Parse TTL string into absolute expiry timestamp.

    Supported: "30m", "2h", "7d", "30d", "forever"
    """
    ttl = ttl.strip().lower()
    if ttl == "forever":
        return None

    multipliers = {"m": 60, "h": 3600, "d": 86400}
    unit = ttl[-1]
    if unit not in multipliers:
        raise ValueError(f"Invalid TTL format: {ttl!r}. Use e.g. '30m', '2h', '7d', 'forever'.")
    try:
        value = int(ttl[:-1])
    except ValueError:
        raise ValueError(f"Invalid TTL format: {ttl!r}. Use e.g. '30m', '2h', '7d', 'forever'.")

    return base_time + value * multipliers[unit]
