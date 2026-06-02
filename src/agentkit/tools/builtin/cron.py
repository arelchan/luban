"""Cron tools — allow the model to create/list/delete scheduled tasks."""

from __future__ import annotations

from datetime import datetime

from agentkit.cron.job import CronJob
from agentkit.cron.scheduler import describe_cron, next_fire_time
from agentkit.tools.builtin.context import _runtime_context
from agentkit.tools.native import tool


@tool(name="cron_create", description="创建定时任务。频率用标准5字段cron表达式或'once'；生命周期如'30m','2h','7d','forever'。")
async def cron_create(cron: str, ttl: str, prompt: str) -> str:
    """Create a scheduled cron job.

    Args:
        cron: Cron expression like '*/5 * * * *', or 'once' for one-shot.
        ttl: Time-to-live like '30m', '2h', '7d', 'forever'.
        prompt: The prompt to execute when triggered.
    """
    ctx = _runtime_context
    if not ctx or "scheduler" not in ctx:
        return "[错误] Cron 调度器未初始化"

    scheduler = ctx["scheduler"]
    try:
        job = CronJob.new(cron=cron, ttl=ttl, prompt=prompt, durable=False)
        scheduler.store.add(job)
    except ValueError as e:
        return f"[错误] {e}"

    desc = describe_cron(job.cron, job.ttl)
    nxt = next_fire_time(job)
    next_str = datetime.fromtimestamp(nxt).strftime("%H:%M") if nxt else "—"
    expire_str = datetime.fromtimestamp(job.expires_at).strftime("%m-%d %H:%M") if job.expires_at else "永久"

    return f"✓ 已创建 [{job.id}] {desc} | {expire_str}过期 | 下次执行：{next_str}\n  prompt: {job.prompt[:60]}"


@tool(name="cron_list", description="查看当前所有定时任务。")
async def cron_list() -> str:
    """List all active cron jobs."""
    ctx = _runtime_context
    if not ctx or "scheduler" not in ctx:
        return "[错误] Cron 调度器未初始化"

    scheduler = ctx["scheduler"]
    jobs = scheduler.store.jobs

    if not jobs:
        return "当前没有活跃的定时任务。"

    lines = ["ID       频率              过期时间      Prompt"]
    for job in jobs:
        desc = describe_cron(job.cron, job.ttl)
        expire_str = datetime.fromtimestamp(job.expires_at).strftime("%m-%d %H:%M") if job.expires_at else "永久"
        durable_mark = " 💾" if job.durable else ""
        lines.append(f"{job.id}   {desc:<16} {expire_str:<12} {job.prompt[:30]}{durable_mark}")

    return "\n".join(lines)


@tool(name="cron_edit", description="编辑已有定时任务的频率、生命周期或提示词。只传需要修改的字段。")
async def cron_edit(id: str, cron: str = "", ttl: str = "", prompt: str = "") -> str:
    """Edit an existing cron job.

    Args:
        id: The job ID to edit.
        cron: New cron expression (optional, leave empty to keep unchanged).
        ttl: New time-to-live (optional, leave empty to keep unchanged).
        prompt: New prompt (optional, leave empty to keep unchanged).
    """
    ctx = _runtime_context
    if not ctx or "scheduler" not in ctx:
        return "[错误] Cron 调度器未初始化"

    scheduler = ctx["scheduler"]
    job = scheduler.store.get(id)

    if not job:
        return f"[错误] 未找到任务 {id}"

    if cron:
        job.cron = cron

    if ttl:
        try:
            from agentkit.cron.job import _parse_ttl
            job.ttl = ttl
            job.expires_at = _parse_ttl(ttl, job.created_at)
        except (ValueError, Exception) as e:
            return f"[错误] 无效的 TTL: {e}"

    if prompt:
        job.prompt = prompt

    # Persist changes (handles durable save internally)
    scheduler.store.update(job)

    desc = describe_cron(job.cron, job.ttl)
    expire_str = datetime.fromtimestamp(job.expires_at).strftime("%m-%d %H:%M") if job.expires_at else "永久"
    return f"✓ 已更新 [{job.id}] {desc} | {expire_str}过期\n  prompt: {job.prompt[:60]}"


@tool(name="cron_delete", description="删除指定的定时任务。")
async def cron_delete(id: str) -> str:
    """Delete a cron job by its ID.

    Args:
        id: The job ID to delete.
    """
    ctx = _runtime_context
    if not ctx or "scheduler" not in ctx:
        return "[错误] Cron 调度器未初始化"

    scheduler = ctx["scheduler"]
    job = scheduler.store.remove(id)
    if job:
        return f"✓ 已删除任务 {id}"
    return f"[错误] 未找到任务 {id}"
