"""SQLite-backed discovery job and article archive store.

The store keeps status and result snapshots in one database so the API does
not depend on Streamlit session state. SQLite connections are short-lived and
all writes are protected; discovery itself remains asynchronous.
"""

from __future__ import annotations

import json
import os
import sqlite3
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class ProgressThrottle:
    """Bound SQLite progress writes while preserving stage changes and completion."""

    def __init__(self, min_interval_seconds: float = 0.3) -> None:
        self.min_interval_seconds = max(0.0, float(min_interval_seconds))
        self._last_at = 0.0
        self._last_stage: str | None = None

    def should_report(
        self,
        stage: str,
        current: int,
        total: int,
        now: float | None = None,
    ) -> bool:
        current_time = time.monotonic() if now is None else float(now)
        stage_changed = stage != self._last_stage
        stage_complete = total > 0 and current >= total
        if (
            not stage_changed
            and not stage_complete
            and current_time - self._last_at < self.min_interval_seconds
        ):
            return False
        self._last_at = current_time
        self._last_stage = stage
        return True


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), default=str)


class JobStore:
    def __init__(self, database_path: str | None = None) -> None:
        default_path = Path(__file__).resolve().parents[1] / "data" / "newstrace.sqlite3"
        self.database_path = Path(database_path or os.getenv("NEWSTRACE_DB_PATH", str(default_path)))
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path, timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA busy_timeout=30000")
        return connection

    def _initialize(self) -> None:
        with self._lock, self._connect() as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.execute("""
                CREATE TABLE IF NOT EXISTS discovery_jobs (
                    id TEXT PRIMARY KEY,
                    outlet TEXT NOT NULL,
                    source_url TEXT,
                    status TEXT NOT NULL,
                    stage TEXT NOT NULL,
                    detail TEXT NOT NULL,
                    current_count INTEGER NOT NULL DEFAULT 0,
                    total_count INTEGER NOT NULL DEFAULT 0,
                    events_json TEXT NOT NULL DEFAULT '[]',
                    parameters_json TEXT NOT NULL DEFAULT '{}',
                    stats_json TEXT NOT NULL DEFAULT '{}',
                    warnings_json TEXT NOT NULL DEFAULT '[]',
                    results_json TEXT NOT NULL DEFAULT '[]',
                    error TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    finished_at TEXT
                )
            """)
            db.execute("CREATE INDEX IF NOT EXISTS idx_jobs_created ON discovery_jobs(created_at DESC)")
            db.execute("CREATE INDEX IF NOT EXISTS idx_jobs_status ON discovery_jobs(status)")

    @staticmethod
    def _decode(row: sqlite3.Row, include_results: bool = False) -> dict[str, Any]:
        result = {
            "job_id": row["id"],
            "outlet": row["outlet"],
            "source_url": row["source_url"],
            "status": row["status"],
            "stage": row["stage"],
            "detail": row["detail"],
            "current": row["current_count"],
            "total": row["total_count"],
            "events": json.loads(row["events_json"] or "[]"),
            "parameters": json.loads(row["parameters_json"] or "{}"),
            "stats": json.loads(row["stats_json"] or "{}"),
            "warnings": json.loads(row["warnings_json"] or "[]"),
            "error": row["error"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
            "finished_at": row["finished_at"],
        }
        if include_results:
            result["articles"] = json.loads(row["results_json"] or "[]")
        return result

    def create_job(self, outlet: str, parameters: dict[str, Any]) -> dict[str, Any]:
        job_id = str(uuid.uuid4())
        now = utc_now()
        initial_event = {
            "stage": "Queued",
            "detail": "Investigation accepted and waiting for a worker.",
            "current": 0,
            "total": 0,
            "at": now,
        }
        with self._lock, self._connect() as db:
            db.execute(
                """INSERT INTO discovery_jobs
                   (id, outlet, status, stage, detail, events_json, parameters_json,
                    created_at, updated_at)
                   VALUES (?, ?, 'queued', 'Queued', ?, ?, ?, ?, ?)""",
                (job_id, outlet, initial_event["detail"], _json([initial_event]),
                 _json(parameters), now, now),
            )
            row = db.execute("SELECT * FROM discovery_jobs WHERE id=?", (job_id,)).fetchone()
        return self._decode(row)

    def get_job(self, job_id: str, include_results: bool = False) -> dict[str, Any] | None:
        with self._lock, self._connect() as db:
            row = db.execute("SELECT * FROM discovery_jobs WHERE id=?", (job_id,)).fetchone()
        return self._decode(row, include_results) if row else None

    def list_jobs(self, limit: int = 20) -> list[dict[str, Any]]:
        with self._lock, self._connect() as db:
            rows = db.execute(
                "SELECT * FROM discovery_jobs ORDER BY created_at DESC LIMIT ?",
                (max(1, min(limit, 100)),),
            ).fetchall()
        return [self._decode(row) for row in rows]

    def update_progress(
        self,
        job_id: str,
        stage: str,
        current: int,
        total: int,
        detail: str,
    ) -> None:
        now = utc_now()
        current = max(0, int(current or 0))
        total = max(0, int(total or 0))
        with self._lock, self._connect() as db:
            row = db.execute(
                "SELECT events_json FROM discovery_jobs WHERE id=?",
                (job_id,),
            ).fetchone()
            if not row:
                return
            events = json.loads(row["events_json"] or "[]")
            event = {
                "stage": str(stage)[:80],
                "detail": str(detail)[:500],
                "current": current,
                "total": total,
                "at": now,
            }
            # Keep a useful event trail without allowing long jobs to grow the DB.
            if not events or any(
                events[-1].get(key) != event.get(key)
                for key in ("stage", "current", "total", "detail")
            ):
                events.append(event)
            events = events[-80:]
            db.execute(
                """UPDATE discovery_jobs
                   SET status='running', stage=?, detail=?, current_count=?, total_count=?,
                       events_json=?, updated_at=?
                   WHERE id=?""",
                (event["stage"], event["detail"], current, total, _json(events), now, job_id),
            )

    def set_source(self, job_id: str, source_url: str, outlet: str | None = None) -> None:
        now = utc_now()
        with self._lock, self._connect() as db:
            db.execute(
                "UPDATE discovery_jobs SET source_url=?, outlet=COALESCE(?, outlet), updated_at=? WHERE id=?",
                (source_url, outlet, now, job_id),
            )

    def complete_job(
        self,
        job_id: str,
        articles: list[dict[str, Any]],
        stats: dict[str, Any],
        warnings: list[str] | None = None,
        partial: bool = False,
    ) -> None:
        now = utc_now()
        status = "partial" if partial else "complete"
        stage = "Complete with some unavailable sources" if partial else "Complete"
        detail = f"{len(articles):,} article records are ready."
        event = {"stage": stage, "detail": detail, "current": len(articles),
                 "total": len(articles), "at": now}
        with self._lock, self._connect() as db:
            row = db.execute(
                "SELECT events_json, outlet, source_url, created_at FROM discovery_jobs WHERE id=?",
                (job_id,),
            ).fetchone()
            if not row:
                return
            events = json.loads(row["events_json"] or "[]")
            events.append(event)
            records = []
            for index, article in enumerate(articles):
                record = dict(article)
                record.setdefault("job_id", job_id)
                record.setdefault("outlet", row["outlet"])
                record.setdefault("source_url", row["source_url"])
                record.setdefault("recorded_at", row["created_at"])
                record.setdefault("article_index", index)
                records.append(record)
            db.execute(
                """UPDATE discovery_jobs SET status=?, stage=?, detail=?,
                   current_count=?, total_count=?, events_json=?, stats_json=?,
                   warnings_json=?, results_json=?, error=NULL, updated_at=?, finished_at=?
                   WHERE id=?""",
                (status, stage, detail, len(records), len(records), _json(events[-80:]),
                 _json(stats), _json(warnings or []), _json(records), now, now, job_id),
            )

    def fail_job(self, job_id: str, error: str, status: str = "failed") -> None:
        now = utc_now()
        safe_error = str(error or "The investigation could not be completed.")[:900]
        event = {
            "stage": "Interrupted" if status == "interrupted" else "Failed",
            "detail": safe_error,
            "current": 0,
            "total": 0,
            "at": now,
        }
        with self._lock, self._connect() as db:
            row = db.execute(
                "SELECT events_json FROM discovery_jobs WHERE id=?",
                (job_id,),
            ).fetchone()
            events = json.loads(row["events_json"] or "[]") if row else []
            events.append(event)
            db.execute(
                """UPDATE discovery_jobs SET status=?, stage=?, detail=?, error=?,
                   events_json=?, updated_at=?, finished_at=? WHERE id=?""",
                (status, event["stage"], safe_error, safe_error,
                 _json(events[-80:]), now, now, job_id),
            )

    def recover_interrupted_jobs(self) -> int:
        """Mark tasks that cannot survive a process restart; never leave them running."""
        now = utc_now()
        with self._lock, self._connect() as db:
            rows = db.execute(
                "SELECT id, events_json FROM discovery_jobs WHERE status IN ('queued','running')"
            ).fetchall()
            for row in rows:
                message = "The API process restarted before this investigation finished. Start a new investigation to retry."
                events = json.loads(row["events_json"] or "[]")
                events.append({
                    "stage": "Interrupted",
                    "detail": message,
                    "current": 0,
                    "total": 0,
                    "at": now,
                })
                db.execute(
                    """UPDATE discovery_jobs SET status='interrupted', stage='Interrupted',
                       detail=?, error=?, events_json=?, updated_at=?, finished_at=? WHERE id=?""",
                    (message, message, _json(events[-80:]), now, now, row["id"]),
                )
        return len(rows)

    def all_articles(self, limit_jobs: int = 30) -> list[dict[str, Any]]:
        with self._lock, self._connect() as db:
            rows = db.execute(
                """SELECT id, outlet, source_url, results_json, created_at
                   FROM discovery_jobs
                   WHERE status IN ('complete','partial')
                   ORDER BY created_at DESC LIMIT ?""",
                (max(1, min(limit_jobs, 100)),),
            ).fetchall()
        records: list[dict[str, Any]] = []
        for row in rows:
            for index, article in enumerate(json.loads(row["results_json"] or "[]")):
                if not isinstance(article, dict):
                    continue
                record = dict(article)
                record.setdefault("job_id", row["id"])
                record.setdefault("outlet", row["outlet"])
                record.setdefault("source_url", row["source_url"])
                record.setdefault("recorded_at", row["created_at"])
                record.setdefault("article_index", index)
                records.append(record)
        return records

    def get_results(self, job_id: str) -> dict[str, Any] | None:
        job = self.get_job(job_id, include_results=True)
        if job is None:
            return None
        return {
            "job_id": job["job_id"],
            "status": job["status"],
            "outlet": job["outlet"],
            "source_url": job["source_url"],
            "articles": job["articles"],
            "stats": job["stats"],
            "warnings": job["warnings"],
        }


store = JobStore()
