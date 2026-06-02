"""Tests for agentkit.cron — job, store, scheduler."""

from __future__ import annotations

import json
import tempfile
import time
from pathlib import Path

import pytest

from agentkit.cron.job import CronJob, _parse_ttl
from agentkit.cron.scheduler import Scheduler, describe_cron, next_fire_time
from agentkit.cron.store import JobStore


class TestParseTtl:
    def test_minutes(self):
        base = 1000.0
        assert _parse_ttl("30m", base) == 1000.0 + 30 * 60

    def test_hours(self):
        base = 1000.0
        assert _parse_ttl("2h", base) == 1000.0 + 2 * 3600

    def test_days(self):
        base = 1000.0
        assert _parse_ttl("7d", base) == 1000.0 + 7 * 86400

    def test_forever(self):
        assert _parse_ttl("forever", 1000.0) is None

    def test_invalid_unit(self):
        with pytest.raises(ValueError):
            _parse_ttl("5x", 0)

    def test_invalid_number(self):
        with pytest.raises(ValueError):
            _parse_ttl("abch", 0)


class TestCronJob:
    def test_new_recurring(self):
        job = CronJob.new(cron="*/5 * * * *", ttl="1h", prompt="check API")
        assert len(job.id) == 6
        assert job.cron == "*/5 * * * *"
        assert job.is_once is False
        assert job.expires_at is not None
        assert job.expires_at == pytest.approx(job.created_at + 3600, abs=1)

    def test_new_once(self):
        job = CronJob.new(cron="once", ttl="2h", prompt="remind me")
        assert job.is_once is True
        assert job.expires_at == pytest.approx(job.created_at + 7200, abs=1)

    def test_new_forever(self):
        job = CronJob.new(cron="0 9 * * *", ttl="forever", prompt="daily summary")
        assert job.expires_at is None
        assert job.is_expired is False

    def test_is_expired(self):
        job = CronJob.new(cron="*/5 * * * *", ttl="1h", prompt="test")
        job.expires_at = time.time() - 10  # Already expired
        assert job.is_expired is True

    def test_serialization_roundtrip(self):
        job = CronJob.new(cron="0 9 * * 1-5", ttl="30d", prompt="hello")
        job.messages = [{"role": "user", "content": "hello"}]
        data = job.to_dict()
        restored = CronJob.from_dict(data)
        assert restored.id == job.id
        assert restored.cron == job.cron
        assert restored.ttl == job.ttl
        assert restored.prompt == job.prompt
        assert restored.messages == job.messages


class TestJobStore:
    def test_add_and_get(self):
        store = JobStore()
        job = CronJob.new(cron="*/5 * * * *", ttl="1h", prompt="test")
        store.add(job)
        assert store.get(job.id) is job
        assert len(store.jobs) == 1

    def test_remove(self):
        store = JobStore()
        job = CronJob.new(cron="*/5 * * * *", ttl="1h", prompt="test")
        store.add(job)
        removed = store.remove(job.id)
        assert removed is job
        assert store.get(job.id) is None

    def test_remove_nonexistent(self):
        store = JobStore()
        assert store.remove("nonexistent") is None

    def test_max_jobs_limit(self):
        store = JobStore()
        for i in range(20):
            store.add(CronJob.new(cron="*/5 * * * *", ttl="1h", prompt=f"job {i}"))
        with pytest.raises(ValueError, match="最多支持"):
            store.add(CronJob.new(cron="*/5 * * * *", ttl="1h", prompt="overflow"))

    def test_remove_expired(self):
        store = JobStore()
        j1 = CronJob.new(cron="*/5 * * * *", ttl="1h", prompt="alive")
        j2 = CronJob.new(cron="*/5 * * * *", ttl="1h", prompt="dead")
        j2.expires_at = time.time() - 10  # Already expired
        store.add(j1)
        store.add(j2)
        expired = store.remove_expired()
        assert len(expired) == 1
        assert expired[0].id == j2.id
        assert len(store.jobs) == 1

    def test_durable_persistence(self):
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            path = Path(f.name)

        store = JobStore(persist_path=path)
        job = CronJob.new(cron="0 9 * * *", ttl="forever", prompt="daily")
        job.durable = True
        store.add(job)

        # Verify file written
        data = json.loads(path.read_text())
        assert len(data) == 1
        assert data[0]["id"] == job.id

        # Load in new store
        store2 = JobStore(persist_path=path)
        count = store2.load_durable()
        assert count == 1
        assert store2.get(job.id).prompt == "daily"

        path.unlink()


class TestScheduler:
    def test_check_due_throttling(self):
        store = JobStore()
        scheduler = Scheduler(store)
        # First call should proceed
        scheduler._last_check = 0
        due = scheduler.check_due()
        assert due == []
        # Immediate second call should be throttled
        due = scheduler.check_due()
        assert due == []

    def test_recurring_job_due(self):
        store = JobStore()
        job = CronJob.new(cron="* * * * *", ttl="1h", prompt="every minute")
        # Pretend it was created 2 minutes ago and never fired
        job.created_at = time.time() - 120
        job.last_fired = 0
        store.add(job)

        scheduler = Scheduler(store)
        scheduler._last_check = 0
        due = scheduler.check_due()
        assert len(due) == 1
        assert due[0].id == job.id

    def test_recurring_job_not_due_yet(self):
        store = JobStore()
        job = CronJob.new(cron="* * * * *", ttl="1h", prompt="every minute")
        # Just fired moments ago
        job.last_fired = time.time()
        store.add(job)

        scheduler = Scheduler(store)
        scheduler._last_check = 0
        due = scheduler.check_due()
        assert len(due) == 0

    def test_once_job_fires_at_expiry(self):
        store = JobStore()
        job = CronJob.new(cron="once", ttl="1h", prompt="remind")
        # Override expires_at to be in the past (should fire now)
        job.expires_at = time.time() - 10
        store.add(job)

        scheduler = Scheduler(store)
        scheduler._last_check = 0
        due = scheduler.check_due()
        assert len(due) == 1

    def test_once_job_already_fired(self):
        store = JobStore()
        job = CronJob.new(cron="once", ttl="1h", prompt="remind")
        job.expires_at = time.time() - 10
        job.last_fired = time.time() - 5  # Already fired
        store.add(job)

        scheduler = Scheduler(store)
        scheduler._last_check = 0
        due = scheduler.check_due()
        assert len(due) == 0

    def test_mark_fired_recurring(self):
        store = JobStore()
        job = CronJob.new(cron="*/5 * * * *", ttl="1h", prompt="test")
        store.add(job)

        scheduler = Scheduler(store)
        scheduler.mark_fired(job)
        assert job.last_fired > 0
        assert store.get(job.id) is not None  # Still exists

    def test_mark_fired_once_removes(self):
        store = JobStore()
        job = CronJob.new(cron="once", ttl="1h", prompt="test")
        store.add(job)

        scheduler = Scheduler(store)
        scheduler.mark_fired(job)
        assert store.get(job.id) is None  # Removed after firing


class TestDescribeCron:
    def test_once(self):
        assert "一次性" in describe_cron("once", "2h")

    def test_common_patterns(self):
        assert describe_cron("*/5 * * * *", "1h") == "每5分钟"
        assert describe_cron("0 * * * *", "1h") == "每小时"
        assert describe_cron("0 9 * * 1-5", "30d") == "工作日09:00"

    def test_custom(self):
        desc = describe_cron("30 14 * * *", "forever")
        assert "14" in desc


class TestNextFireTime:
    def test_recurring(self):
        job = CronJob.new(cron="* * * * *", ttl="1h", prompt="test")
        job.created_at = time.time() - 120
        nxt = next_fire_time(job)
        assert nxt is not None
        assert nxt > job.created_at

    def test_once_not_fired(self):
        job = CronJob.new(cron="once", ttl="2h", prompt="test")
        nxt = next_fire_time(job)
        assert nxt == job.expires_at

    def test_once_already_fired(self):
        job = CronJob.new(cron="once", ttl="2h", prompt="test")
        job.last_fired = time.time()
        nxt = next_fire_time(job)
        assert nxt is None
