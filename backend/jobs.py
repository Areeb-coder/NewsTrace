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
    backend_name = "sqlite"
    is_durable = False

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

    def check_connection(self) -> tuple[bool, str]:
        try:
            with self._connect() as db:
                db.execute("SELECT 1").fetchone()
            return True, "SQLite job store is available."
        except Exception as exc:
            return False, f"SQLite job store is unavailable: {type(exc).__name__}: {exc}"

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
                "SELECT events_json, current_count, total_count FROM discovery_jobs WHERE id=?",
                (job_id,),
            ).fetchone()
            events = json.loads(row["events_json"] or "[]") if row else []
            current = int(row["current_count"] or 0) if row else 0
            total = int(row["total_count"] or 0) if row else 0
            event["current"] = current
            event["total"] = total
            events.append(event)
            db.execute(
                """UPDATE discovery_jobs SET status=?, stage=?, detail=?, error=?,
                   current_count=?, total_count=?, events_json=?, updated_at=?, finished_at=?
                   WHERE id=?""",
                (status, event["stage"], safe_error, safe_error, current, total,
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




class SupabaseJobStore:
    """Durable job/archive store backed by a private Supabase Postgres table.

    The service-role key is read only by this backend. The table should have
    RLS enabled with no anon/authenticated policies; service_role bypasses RLS.
    JSON columns use native Postgres JSONB values, not stringified JSON.
    """

    backend_name = "supabase"
    is_durable = True
    table_name = "newstrace_discovery_jobs"

    def __init__(self, url: str, service_role_key: str, client: Any = None) -> None:
        if client is None:
            from supabase import create_client
            client = create_client(url, service_role_key)
        self.client = client
        self._lock = threading.RLock()

    @staticmethod
    def _json_value(value: Any, default: Any) -> Any:
        if value is None:
            return default
        if isinstance(value, str):
            try:
                return json.loads(value)
            except (TypeError, ValueError):
                return default
        return value

    @classmethod
    def _decode(cls, row: dict[str, Any], include_results: bool = False) -> dict[str, Any]:
        result = {
            "job_id": row["id"],
            "outlet": row.get("outlet") or "",
            "source_url": row.get("source_url"),
            "status": row.get("status") or "queued",
            "stage": row.get("stage") or "Queued",
            "detail": row.get("detail") or "",
            "current": int(row.get("current_count") or 0),
            "total": int(row.get("total_count") or 0),
            "events": cls._json_value(row.get("events_json"), []),
            "parameters": cls._json_value(row.get("parameters_json"), {}),
            "stats": cls._json_value(row.get("stats_json"), {}),
            "warnings": cls._json_value(row.get("warnings_json"), []),
            "error": row.get("error"),
            "created_at": row.get("created_at"),
            "updated_at": row.get("updated_at"),
            "finished_at": row.get("finished_at"),
        }
        if include_results:
            result["articles"] = cls._json_value(row.get("results_json"), [])
        return result

    def check_connection(self) -> tuple[bool, str]:
        try:
            self.client.table(self.table_name).select("id").limit(1).execute()
            return True, "Supabase durable job store is available."
        except Exception as exc:
            return False, (
                "Supabase job storage is unavailable. Apply "
                "supabase/migrations/20261106_newstrace_discovery_jobs.sql and verify "
                f"SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY. ({type(exc).__name__}: {exc})"
            )

    def _get_row(self, job_id: str) -> dict[str, Any] | None:
        response = (
            self.client.table(self.table_name)
            .select("*")
            .eq("id", job_id)
            .limit(1)
            .execute()
        )
        rows = response.data or []
        return rows[0] if rows else None

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
        record = {
            "id": job_id,
            "outlet": outlet,
            "source_url": None,
            "status": "queued",
            "stage": "Queued",
            "detail": initial_event["detail"],
            "current_count": 0,
            "total_count": 0,
            "events_json": [initial_event],
            "parameters_json": parameters,
            "stats_json": {},
            "warnings_json": [],
            "results_json": [],
            "error": None,
            "created_at": now,
            "updated_at": now,
            "finished_at": None,
        }
        self.client.table(self.table_name).insert(record).execute()
        row = self._get_row(job_id) or record
        return self._decode(row)

    def get_job(self, job_id: str, include_results: bool = False) -> dict[str, Any] | None:
        row = self._get_row(job_id)
        return self._decode(row, include_results) if row else None

    def list_jobs(self, limit: int = 20) -> list[dict[str, Any]]:
        response = (
            self.client.table(self.table_name)
            .select("*")
            .order("created_at", desc=True)
            .limit(max(1, min(int(limit), 100)))
            .execute()
        )
        return [self._decode(row) for row in (response.data or [])]

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
        with self._lock:
            row = self._get_row(job_id)
            if not row:
                return
            events = self._json_value(row.get("events_json"), [])
            event = {
                "stage": str(stage)[:80],
                "detail": str(detail)[:500],
                "current": current,
                "total": total,
                "at": now,
            }
            if not events or any(
                events[-1].get(key) != event.get(key)
                for key in ("stage", "current", "total", "detail")
            ):
                events.append(event)
            self.client.table(self.table_name).update({
                "status": "running",
                "stage": event["stage"],
                "detail": event["detail"],
                "current_count": current,
                "total_count": total,
                "events_json": events[-80:],
                "updated_at": now,
            }).eq("id", job_id).execute()

    def set_source(self, job_id: str, source_url: str, outlet: str | None = None) -> None:
        payload: dict[str, Any] = {
            "source_url": source_url,
            "updated_at": utc_now(),
        }
        if outlet:
            payload["outlet"] = outlet
        self.client.table(self.table_name).update(payload).eq("id", job_id).execute()

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
        with self._lock:
            row = self._get_row(job_id)
            if not row:
                return
            events = self._json_value(row.get("events_json"), [])
            events.append({
                "stage": stage,
                "detail": detail,
                "current": len(articles),
                "total": len(articles),
                "at": now,
            })
            outlet = row.get("outlet") or ""
            source_url = row.get("source_url")
            created_at = row.get("created_at") or now
            records = []
            for index, article in enumerate(articles):
                record = dict(article)
                record.setdefault("job_id", job_id)
                record.setdefault("outlet", outlet)
                record.setdefault("source_url", source_url)
                record.setdefault("recorded_at", created_at)
                record.setdefault("article_index", index)
                records.append(record)

            self.client.table(self.table_name).update({
                "status": status,
                "stage": stage,
                "detail": detail,
                "current_count": len(records),
                "total_count": len(records),
                "events_json": events[-80:],
                "stats_json": stats,
                "warnings_json": warnings or [],
                "results_json": records,
                "error": None,
                "updated_at": now,
                "finished_at": now,
            }).eq("id", job_id).execute()

    def fail_job(self, job_id: str, error: str, status: str = "failed") -> None:
        now = utc_now()
        safe_error = str(error or "The investigation could not be completed.")[:900]
        with self._lock:
            row = self._get_row(job_id)
            if not row:
                return
            current = int(row.get("current_count") or 0)
            total = int(row.get("total_count") or 0)
            events = self._json_value(row.get("events_json"), [])
            events.append({
                "stage": "Interrupted" if status == "interrupted" else "Failed",
                "detail": safe_error,
                "current": current,
                "total": total,
                "at": now,
            })
            self.client.table(self.table_name).update({
                "status": status,
                "stage": "Interrupted" if status == "interrupted" else "Failed",
                "detail": safe_error,
                "error": safe_error,
                "current_count": current,
                "total_count": total,
                "events_json": events[-80:],
                "updated_at": now,
                "finished_at": now,
            }).eq("id", job_id).execute()

    def recover_interrupted_jobs(self) -> int:
        response = (
            self.client.table(self.table_name)
            .select("id,events_json,current_count,total_count")
            .in_("status", ["queued", "running"])
            .execute()
        )
        rows = response.data or []
        now = utc_now()
        for row in rows:
            message = (
                "The API process restarted before this investigation finished. "
                "Start a new investigation to retry."
            )
            events = self._json_value(row.get("events_json"), [])
            events.append({
                "stage": "Interrupted",
                "detail": message,
                "current": int(row.get("current_count") or 0),
                "total": int(row.get("total_count") or 0),
                "at": now,
            })
            self.client.table(self.table_name).update({
                "status": "interrupted",
                "stage": "Interrupted",
                "detail": message,
                "error": message,
                "events_json": events[-80:],
                "updated_at": now,
                "finished_at": now,
            }).eq("id", row["id"]).execute()
        return len(rows)

    def all_articles(self, limit_jobs: int = 100) -> list[dict[str, Any]]:
        response = (
            self.client.table(self.table_name)
            .select("id,outlet,source_url,results_json,created_at")
            .in_("status", ["complete", "partial"])
            .order("created_at", desc=True)
            .limit(max(1, min(int(limit_jobs), 1000)))
            .execute()
        )
        records: list[dict[str, Any]] = []
        seen: set[str] = set()
        for row in response.data or []:
            articles = self._json_value(row.get("results_json"), [])
            for index, article in enumerate(articles):
                if not isinstance(article, dict):
                    continue
                record = dict(article)
                record.setdefault("job_id", row["id"])
                record.setdefault("outlet", row.get("outlet"))
                record.setdefault("source_url", row.get("source_url"))
                record.setdefault("recorded_at", row.get("created_at"))
                record.setdefault("article_index", index)
                url = str(record.get("url") or "").strip().lower().rstrip("/")
                identity = url or "|".join((
                    str(record.get("outlet") or "").casefold(),
                    str(record.get("title") or "").casefold(),
                    str(record.get("date") or ""),
                ))
                if identity in seen:
                    continue
                seen.add(identity)
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


def create_job_store() -> JobStore | SupabaseJobStore:
    """Use durable Supabase storage when configured; keep SQLite for local development."""
    url = os.getenv("SUPABASE_URL", "").strip()
    service_role_key = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "").strip()
    require_durable = os.getenv("NEWSTRACE_REQUIRE_DURABLE_STORE", "false").lower() in {
        "1", "true", "yes", "on"
    }

    if url and service_role_key:
        return SupabaseJobStore(url, service_role_key)

    if require_durable:
        raise RuntimeError(
            "Durable storage is required but is not configured. Set SUPABASE_URL and "
            "SUPABASE_SERVICE_ROLE_KEY, then apply the SQL in "
            "supabase/migrations/20261106_newstrace_discovery_jobs.sql."
        )
    return JobStore()


store = create_job_store()
