"""JobStore — in-memory + optional JSON persistence for cron jobs."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from agentkit.cron.job import CronJob

logger = logging.getLogger(__name__)

# Default path for durable jobs
_DEFAULT_PATH = Path.home() / ".agentkit" / "cron.json"
_MAX_JOBS = 20


class JobStore:
    """Manages cron jobs (session-only in memory, durable on disk)."""

    def __init__(self, persist_path: Path | None = None):
        self._jobs: dict[str, CronJob] = {}
        self._persist_path = persist_path or _DEFAULT_PATH

    @property
    def jobs(self) -> list[CronJob]:
        return list(self._jobs.values())

    def get(self, job_id: str) -> CronJob | None:
        return self._jobs.get(job_id)

    def add(self, job: CronJob) -> None:
        """Add a job. Raises ValueError if at capacity."""
        if len(self._jobs) >= _MAX_JOBS:
            raise ValueError(f"最多支持 {_MAX_JOBS} 个活跃任务，请先删除旧任务。")
        self._jobs[job.id] = job
        if job.durable:
            self._save_durable()

    def remove(self, job_id: str) -> CronJob | None:
        """Remove a job by ID. Returns the removed job or None."""
        job = self._jobs.pop(job_id, None)
        if job and job.durable:
            self._save_durable()
        return job

    def update(self, job: CronJob) -> None:
        """Update a job (e.g., after firing). Persists if durable."""
        self._jobs[job.id] = job
        if job.durable:
            self._save_durable()

    def remove_expired(self) -> list[CronJob]:
        """Remove and return all expired jobs."""
        expired = [j for j in self._jobs.values() if j.is_expired]
        for j in expired:
            self._jobs.pop(j.id, None)
        if any(j.durable for j in expired):
            self._save_durable()
        return expired

    def load_durable(self) -> int:
        """Load durable jobs from disk. Returns count loaded."""
        if not self._persist_path.exists():
            return 0
        try:
            data = json.loads(self._persist_path.read_text(encoding="utf-8"))
            count = 0
            for item in data:
                job = CronJob.from_dict(item)
                job.durable = True
                self._jobs[job.id] = job
                count += 1
            logger.info("Loaded %d durable cron jobs", count)
            return count
        except (json.JSONDecodeError, KeyError) as e:
            logger.warning("Failed to load cron.json: %s", e)
            return 0

    def _save_durable(self) -> None:
        """Persist all durable jobs to disk."""
        durable_jobs = [j.to_dict() for j in self._jobs.values() if j.durable]
        self._persist_path.parent.mkdir(parents=True, exist_ok=True)
        self._persist_path.write_text(
            json.dumps(durable_jobs, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
