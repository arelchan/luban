"""Scheduler — checks due jobs and coordinates execution."""

from __future__ import annotations

import logging
import time

from croniter import croniter

from agentkit.cron.job import CronJob
from agentkit.cron.store import JobStore

logger = logging.getLogger(__name__)


# System prompt suffix for cron execution mode
CRON_SYSTEM_SUFFIX = """
---
[执行模式：定时任务]
你正在执行一个自动化定时任务，不是与用户实时对话。
- 任务ID：{job_id}
- 频率：{schedule_desc}
- 已执行次数：{exec_count}

行为要求：
- 直接执行任务，不要寒暄或确认
- 输出简洁，只报告结果和异常
- 发现状态变化或异常时明确标注
- 不要反问用户（用户可能不在线）
- 需要工具时直接调用
- 高风险写操作（删除文件、force push 等）跳过并说明
"""


class Scheduler:
    """Cron scheduler that integrates with the REPL idle loop."""

    def __init__(self, store: JobStore):
        self._store = store
        self._last_check: float = 0
        self._check_interval: float = 30.0  # Check every 30s

    @property
    def store(self) -> JobStore:
        return self._store

    def check_due(self) -> list[CronJob]:
        """Check for due jobs. Called from REPL idle loop.

        Returns list of jobs that should fire now.
        """
        now = time.time()

        # Throttle checks
        if now - self._last_check < self._check_interval:
            return []
        self._last_check = now

        # Remove expired jobs first
        expired = self._store.remove_expired()
        for j in expired:
            logger.info("Cron job %s expired and removed", j.id)

        # Find due jobs
        due: list[CronJob] = []
        for job in self._store.jobs:
            if job.is_expired:
                continue
            if self._is_due(job, now):
                due.append(job)

        return due

    def _is_due(self, job: CronJob, now: float) -> bool:
        """Determine if a job should fire at the given time."""
        if job.is_once:
            # One-shot: fire when expires_at is reached (ttl = delay)
            # For once jobs, expires_at IS the fire time
            if job.last_fired > 0:
                return False  # Already fired
            if job.expires_at and now >= job.expires_at:
                return True
            return False

        # Recurring: check cron expression
        base = job.last_fired if job.last_fired > 0 else job.created_at

        try:
            cron = croniter(job.cron, base)
            next_fire = cron.get_next(float)
            return now >= next_fire
        except (ValueError, KeyError):
            logger.warning("Invalid cron expression for job %s: %s", job.id, job.cron)
            return False

    def mark_fired(self, job: CronJob) -> None:
        """Mark a job as having just fired."""
        job.last_fired = time.time()
        if job.is_once:
            # One-shot: remove after firing
            self._store.remove(job.id)
        else:
            self._store.update(job)

    def build_cron_system_suffix(self, job: CronJob) -> str:
        """Build the cron execution mode system prompt suffix."""
        exec_count = len(job.messages) // 2  # pairs of user+assistant
        return CRON_SYSTEM_SUFFIX.format(
            job_id=job.id,
            schedule_desc=describe_cron(job.cron, job.ttl),
            exec_count=exec_count,
        )


def describe_cron(cron: str, ttl: str) -> str:
    """Human-readable description of a cron schedule."""
    if cron == "once":
        return f"一次性（{ttl}后触发）"

    # Common patterns
    _COMMON = {
        "* * * * *": "每分钟",
        "*/5 * * * *": "每5分钟",
        "*/10 * * * *": "每10分钟",
        "*/15 * * * *": "每15分钟",
        "*/30 * * * *": "每30分钟",
        "0 * * * *": "每小时",
        "0 */2 * * *": "每2小时",
        "0 9 * * *": "每天09:00",
        "0 18 * * *": "每天18:00",
        "0 9 * * 1-5": "工作日09:00",
        "0 0 * * *": "每天00:00",
    }
    if cron in _COMMON:
        return _COMMON[cron]

    # Parse for basic description
    parts = cron.split()
    if len(parts) != 5:
        return cron

    minute, hour, dom, month, dow = parts

    desc_parts = []
    if dow != "*":
        dow_names = {"1": "一", "2": "二", "3": "三", "4": "四", "5": "五", "6": "六", "0": "日", "7": "日"}
        if dow == "1-5":
            desc_parts.append("工作日")
        elif dow == "6,0" or dow == "0,6":
            desc_parts.append("周末")
        else:
            desc_parts.append(f"周{dow_names.get(dow, dow)}")

    if hour != "*" and minute != "*":
        desc_parts.append(f"{hour}:{minute.zfill(2)}")
    elif hour != "*":
        desc_parts.append(f"每天{hour}点")
    elif minute.startswith("*/"):
        desc_parts.append(f"每{minute[2:]}分钟")

    return " ".join(desc_parts) if desc_parts else cron


def next_fire_time(job: CronJob) -> float | None:
    """Calculate next fire timestamp for a job."""
    if job.is_once:
        if job.last_fired > 0:
            return None  # Already fired
        return job.expires_at

    base = job.last_fired if job.last_fired > 0 else job.created_at
    try:
        cron = croniter(job.cron, base)
        return cron.get_next(float)
    except (ValueError, KeyError):
        return None
