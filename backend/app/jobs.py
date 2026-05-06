"""Job tracking with stdlib sqlite3.

No ORM, no async DB lib, no rate limiter. Sqlite is sync but each call is
millisecond-fast for our row counts; we accept the brief block.

Job lifecycle: insert on start, update on finish. The job row is the source
of truth; everything else (recent jobs, today's count) is a simple SELECT.

We do NOT preemptively rate-limit. NVIDIA's 429 is what tells us we hit a
limit, and we surface that error verbatim to the UI. Pre-pacing was the
biggest source of complexity in v0 with no real benefit at our usage level.
"""
from __future__ import annotations

import logging
import sqlite3
import threading
import uuid
from datetime import datetime, timezone
from typing import Any

from .settings import settings

log = logging.getLogger("ddstudio.jobs")

# One connection, one lock. sqlite3 is fine for single-writer workloads.
_lock = threading.Lock()
_conn = sqlite3.connect(str(settings.db_path), check_same_thread=False)
_conn.row_factory = sqlite3.Row
_conn.execute("PRAGMA journal_mode=WAL")
_conn.execute("""
    CREATE TABLE IF NOT EXISTS jobs (
        id              TEXT PRIMARY KEY,
        kind            TEXT NOT NULL,        -- 'preview' | 'create'
        mode            TEXT NOT NULL,        -- 'hosted' | 'local'
        model           TEXT NOT NULL,
        schema_hash     TEXT NOT NULL,
        schema_name     TEXT NOT NULL DEFAULT '',
        num_records     INTEGER NOT NULL,
        est_llm_calls   INTEGER NOT NULL DEFAULT 0,
        actual_llm_calls INTEGER NOT NULL DEFAULT 0,
        started_at      TEXT NOT NULL,
        finished_at     TEXT,
        status          TEXT NOT NULL,        -- 'running' | 'complete' | 'failed'
        error           TEXT,
        dataset_path    TEXT
    )
""")
_conn.execute("CREATE INDEX IF NOT EXISTS idx_jobs_started ON jobs(started_at DESC)")
_conn.commit()


def new_job_id(kind: str) -> str:
    """Generate a job_id with a stable prefix so logs grep cleanly."""
    prefix = "prev" if kind == "preview" else "job"
    return f"{prefix}_{uuid.uuid4().hex[:10]}"


def record_start(
    *, job_id: str, kind: str, mode: str, model: str,
    schema_hash: str, schema_name: str,
    num_records: int, est_llm_calls: int,
) -> None:
    with _lock:
        _conn.execute(
            "INSERT INTO jobs (id, kind, mode, model, schema_hash, schema_name, "
            "num_records, est_llm_calls, started_at, status) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'running')",
            (job_id, kind, mode, model, schema_hash, schema_name,
             num_records, est_llm_calls,
             datetime.now(timezone.utc).isoformat()),
        )
        _conn.commit()
    log.info("job started", extra={
        "job_id": job_id, "kind": kind, "mode": mode, "model": model,
        "num_records": num_records, "est_llm_calls": est_llm_calls,
    })


def record_finish(
    *, job_id: str, status: str,
    actual_llm_calls: int = 0, error: str | None = None,
    dataset_path: str | None = None,
) -> None:
    with _lock:
        _conn.execute(
            "UPDATE jobs SET finished_at=?, status=?, actual_llm_calls=?, "
            "error=?, dataset_path=? WHERE id=?",
            (datetime.now(timezone.utc).isoformat(), status,
             actual_llm_calls, error, dataset_path, job_id),
        )
        _conn.commit()
    log.info("job finished", extra={
        "job_id": job_id, "status": status, "actual_llm_calls": actual_llm_calls,
        **({"error": error} if error else {}),
    })


def _row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    return {k: row[k] for k in row.keys()}


def recent(limit: int = 50) -> list[dict[str, Any]]:
    with _lock:
        rows = _conn.execute(
            "SELECT * FROM jobs ORDER BY started_at DESC LIMIT ?", (limit,),
        ).fetchall()
    return [_row_to_dict(r) for r in rows]


def get(job_id: str) -> dict[str, Any] | None:
    with _lock:
        row = _conn.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
    return _row_to_dict(row) if row else None


def stats_today(mode: str) -> dict[str, Any]:
    """Today's count for the budget panel. UTC day boundary - good enough."""
    today = datetime.now(timezone.utc).replace(
        hour=0, minute=0, second=0, microsecond=0,
    ).isoformat()
    with _lock:
        rows = _conn.execute(
            "SELECT COUNT(*) AS n, COALESCE(SUM(actual_llm_calls), 0) AS calls "
            "FROM jobs WHERE started_at >= ? AND mode = ?",
            (today, mode),
        ).fetchone()
    return {"jobs_today": rows["n"], "llm_calls_today": rows["calls"]}


def recent_errors(limit: int = 50) -> list[dict[str, Any]]:
    with _lock:
        rows = _conn.execute(
            "SELECT * FROM jobs WHERE status='failed' "
            "ORDER BY finished_at DESC LIMIT ?", (limit,),
        ).fetchall()
    return [_row_to_dict(r) for r in rows]
