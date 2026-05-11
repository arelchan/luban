"""Background data cleanup — removes stale trace/session files on startup.

Runs once per startup in a background thread; never blocks the main flow.
Retention periods are configured via DataConfig:
  trace_retention_days   — delete daily trace files older than N days
  session_retention_days — delete session files older than N days (0 = keep forever)

Trace cleanup:
  ~/.agentkit/sessions/traces/<session_id>/<date>.jsonl  → delete if date < cutoff
  Legacy <date>.json files are also cleaned up.
  Empty trace session directories are removed after file cleanup.

Session cleanup:
  ~/.agentkit/sessions/sess_*.json → delete if last-modified older than N days
  Corresponding index entry is also removed.
"""

from __future__ import annotations

import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path

from agentkit.audit import audit

_SESSIONS_DIR = Path("~/.agentkit/sessions").expanduser()


def _cleanup_traces(retention_days: int) -> None:
    if retention_days <= 0:
        return
    traces_root = _SESSIONS_DIR / "traces"
    if not traces_root.exists():
        return

    cutoff = datetime.now() - timedelta(days=retention_days)
    cutoff_str = cutoff.strftime("%Y-%m-%d")
    deleted_files = 0
    deleted_dirs = 0

    for session_dir in traces_root.iterdir():
        if not session_dir.is_dir():
            continue
        for trace_file in list(session_dir.glob("*.json")) + list(session_dir.glob("*.jsonl")):
            # filename format: 2026-05-08.jsonl (or legacy .json)
            if trace_file.stem < cutoff_str:
                try:
                    trace_file.unlink()
                    deleted_files += 1
                except OSError:
                    pass
        # Remove empty session trace directory
        try:
            if not any(session_dir.iterdir()):
                session_dir.rmdir()
                deleted_dirs += 1
        except OSError:
            pass

    if deleted_files > 0:
        audit(
            "cleanup",
            "trace.cleanup",
            data={"deleted_files": deleted_files, "deleted_dirs": deleted_dirs,
                  "retention_days": retention_days},
        )


def _cleanup_sessions(retention_days: int) -> None:
    if retention_days <= 0:
        return
    if not _SESSIONS_DIR.exists():
        return

    cutoff = datetime.now(timezone.utc) - timedelta(days=retention_days)
    deleted = []

    for sess_file in _SESSIONS_DIR.glob("sess_*.json"):
        try:
            mtime = datetime.fromtimestamp(sess_file.stat().st_mtime, tz=timezone.utc)
            if mtime < cutoff:
                session_id = sess_file.stem.removeprefix("sess_")
                sess_file.unlink()
                deleted.append(session_id)
        except OSError:
            pass

    if not deleted:
        return

    # Remove deleted sessions from index
    index_path = _SESSIONS_DIR / "index.json"
    if index_path.exists():
        try:
            import json
            data = json.loads(index_path.read_text(encoding="utf-8"))
            data = [s for s in data if s.get("id") not in deleted]
            index_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception:
            pass

    audit(
        "cleanup",
        "session.cleanup",
        data={"deleted": len(deleted), "retention_days": retention_days},
    )


def run_cleanup(trace_retention_days: int, session_retention_days: int) -> None:
    """Run cleanup in a background daemon thread. Returns immediately."""
    def _run():
        try:
            _cleanup_traces(trace_retention_days)
            _cleanup_sessions(session_retention_days)
        except Exception as e:
            audit("cleanup", "cleanup.error", status="error", error=str(e))

    t = threading.Thread(target=_run, daemon=True, name="luban-cleanup")
    t.start()
