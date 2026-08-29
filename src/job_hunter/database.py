from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .models import Job

APPLICATION_STATUSES = {"NEW", "SHORTLISTED", "CV_GENERATED", "APPROVED_TO_APPLY", "APPLIED", "SKIPPED"}

JOBS_SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT NOT NULL, company TEXT NOT NULL,
    location TEXT NOT NULL, work_mode TEXT NOT NULL, description TEXT NOT NULL,
    source TEXT NOT NULL, url TEXT NOT NULL UNIQUE, published_at TEXT,
    discovered_at TEXT NOT NULL, score REAL NOT NULL,
    decision TEXT NOT NULL CHECK (decision IN ('APPLY', 'REVIEW', 'REJECT')),
    reasons TEXT NOT NULL, created_at TEXT NOT NULL,
    application_status TEXT NOT NULL DEFAULT 'NEW', first_seen_at TEXT,
    last_seen_at TEXT, last_scored_at TEXT, cv_generated_at TEXT, applied_at TEXT
)
"""

RUNS_SCHEMA = """
CREATE TABLE IF NOT EXISTS discovery_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT, started_at TEXT NOT NULL, finished_at TEXT,
    status TEXT NOT NULL, sources TEXT NOT NULL, preliminary INTEGER NOT NULL DEFAULT 0,
    new_jobs INTEGER NOT NULL DEFAULT 0, updated_jobs INTEGER NOT NULL DEFAULT 0,
    duplicates INTEGER NOT NULL DEFAULT 0, apply_count INTEGER NOT NULL DEFAULT 0,
    review_count INTEGER NOT NULL DEFAULT 0, reject_count INTEGER NOT NULL DEFAULT 0,
    errors TEXT NOT NULL DEFAULT '{}'
)
"""


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class JobDatabase:
    def __init__(self, path: str | Path):
        self.path = Path(path); self.path.parent.mkdir(parents=True, exist_ok=True); self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path); connection.row_factory = sqlite3.Row; return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.execute(JOBS_SCHEMA); connection.execute(RUNS_SCHEMA)
            columns = {row[1] for row in connection.execute("PRAGMA table_info(jobs)")}
            migrations = {
                "published_at": "TEXT", "discovered_at": "TEXT", "application_status": "TEXT NOT NULL DEFAULT 'NEW'",
                "first_seen_at": "TEXT", "last_seen_at": "TEXT", "last_scored_at": "TEXT",
                "cv_generated_at": "TEXT", "applied_at": "TEXT",
            }
            for name, definition in migrations.items():
                if name not in columns: connection.execute(f"ALTER TABLE jobs ADD COLUMN {name} {definition}")
            connection.execute("UPDATE jobs SET discovered_at = COALESCE(discovered_at, created_at)")
            connection.execute("UPDATE jobs SET application_status = COALESCE(application_status, 'NEW')")
            connection.execute("UPDATE jobs SET first_seen_at = COALESCE(first_seen_at, discovered_at, created_at)")
            connection.execute("UPDATE jobs SET last_seen_at = COALESCE(last_seen_at, discovered_at, created_at)")
            connection.execute("UPDATE jobs SET last_scored_at = COALESCE(last_scored_at, discovered_at, created_at)")

    def upsert(self, job: Job) -> bool:
        seen_at = job.discovered_at or utc_now()
        values = (job.title, job.company, job.location, job.work_mode, job.description, job.source, job.url,
                  job.published_at, seen_at, job.score, job.decision, json.dumps(job.reasons, ensure_ascii=False),
                  job.created_at, seen_at, seen_at, seen_at)
        with self._connect() as connection:
            existed = connection.execute("SELECT 1 FROM jobs WHERE url = ?", (job.url,)).fetchone()
            connection.execute("""
                INSERT INTO jobs (title, company, location, work_mode, description, source, url, published_at,
                    discovered_at, score, decision, reasons, created_at, first_seen_at, last_seen_at, last_scored_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(url) DO UPDATE SET
                    title=excluded.title, company=excluded.company, location=excluded.location,
                    work_mode=excluded.work_mode, description=excluded.description, source=excluded.source,
                    published_at=excluded.published_at, score=excluded.score, decision=excluded.decision,
                    reasons=excluded.reasons, last_seen_at=excluded.last_seen_at,
                    last_scored_at=excluded.last_scored_at
            """, values)
        return existed is None

    def list_jobs(self, view: str | None = None) -> list[dict[str, Any]]:
        clauses = {
            "today": "date(first_seen_at, 'localtime') = date('now', 'localtime')",
            "recommended": "decision = 'APPLY' AND application_status NOT IN ('APPLIED','SKIPPED')",
            "review": "decision = 'REVIEW' AND application_status NOT IN ('APPLIED','SKIPPED')",
            "cvs": "application_status = 'CV_GENERATED'",
            "applied": "application_status = 'APPLIED'",
            "discarded": "decision = 'REJECT' OR application_status = 'SKIPPED'",
        }
        where = f"WHERE {clauses[view]}" if view in clauses else ""
        with self._connect() as connection:
            rows = connection.execute(f"""SELECT * FROM jobs {where} ORDER BY
                CASE decision WHEN 'APPLY' THEN 0 WHEN 'REVIEW' THEN 1 ELSE 2 END,
                score DESC, COALESCE(published_at, '') DESC, id DESC""").fetchall()
        return [dict(row) for row in rows]

    def get_job_row(self, job_id: int) -> dict[str, Any] | None:
        with self._connect() as connection: row = connection.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
        return dict(row) if row else None

    def get_job(self, job_id: int | None = None, url: str | None = None) -> Job | None:
        if job_id is None and url is None: raise ValueError("job_id or url is required")
        query, value = ("id = ?", job_id) if job_id is not None else ("url = ?", url)
        with self._connect() as connection: row = connection.execute(f"SELECT * FROM jobs WHERE {query}", (value,)).fetchone()
        if row is None: return None
        data = dict(row)
        return Job(title=data["title"], company=data["company"], location=data["location"], work_mode=data["work_mode"],
                   description=data["description"], source=data["source"], url=data["url"], published_at=data.get("published_at"),
                   discovered_at=data.get("discovered_at") or data["created_at"], id=data["id"], score=data["score"],
                   decision=data["decision"], reasons=json.loads(data["reasons"]), created_at=data["created_at"])

    def set_application_status(self, job_id: int, status: str, at: str | None = None) -> None:
        if status not in APPLICATION_STATUSES: raise ValueError(f"Invalid application status: {status}")
        timestamp = at or utc_now(); assignments = ["application_status = ?"]; values: list[Any] = [status]
        if status == "CV_GENERATED":
            assignments[0] = "application_status = CASE WHEN application_status IN ('APPROVED_TO_APPLY','APPLIED') THEN application_status ELSE ? END"
            assignments.append("cv_generated_at = ?"); values.append(timestamp)
        if status == "APPLIED": assignments.append("applied_at = ?"); values.append(timestamp)
        values.append(job_id)
        with self._connect() as connection:
            cursor = connection.execute(f"UPDATE jobs SET {', '.join(assignments)} WHERE id = ?", values)
            if cursor.rowcount != 1: raise KeyError(f"Job not found: {job_id}")

    def dashboard_counts(self) -> dict[str, int]:
        with self._connect() as connection:
            row = connection.execute("""SELECT
              SUM(date(first_seen_at,'localtime')=date('now','localtime')) AS new_today,
              SUM(decision='APPLY' AND application_status NOT IN ('APPLIED','SKIPPED')) AS recommended,
              SUM(decision='REVIEW' AND application_status NOT IN ('APPLIED','SKIPPED')) AS review,
              SUM(application_status='CV_GENERATED') AS cvs,
              SUM(application_status='APPLIED') AS applied,
              SUM(decision='REJECT' OR application_status='SKIPPED') AS discarded FROM jobs""").fetchone()
        return {key: int(row[key] or 0) for key in row.keys()}

    def create_discovery_run(self, sources: list[str], started_at: str | None = None) -> int:
        with self._connect() as connection:
            cursor = connection.execute("INSERT INTO discovery_runs (started_at,status,sources) VALUES (?,?,?)",
                                        (started_at or utc_now(), "RUNNING", json.dumps(sources)))
            return int(cursor.lastrowid)

    def finish_discovery_run(self, run_id: int, *, status: str, preliminary: int = 0, new_jobs: int = 0,
                             updated_jobs: int = 0, duplicates: int = 0, apply_count: int = 0,
                             review_count: int = 0, reject_count: int = 0, errors: dict | None = None) -> None:
        with self._connect() as connection:
            connection.execute("""UPDATE discovery_runs SET finished_at=?,status=?,preliminary=?,new_jobs=?,updated_jobs=?,
                duplicates=?,apply_count=?,review_count=?,reject_count=?,errors=? WHERE id=?""",
                (utc_now(), status, preliminary, new_jobs, updated_jobs, duplicates, apply_count,
                 review_count, reject_count, json.dumps(errors or {}, ensure_ascii=False), run_id))

    def list_discovery_runs(self, limit: int = 50) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute("SELECT * FROM discovery_runs ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
        return [dict(row) for row in rows]

    def latest_discovery_run(self) -> dict[str, Any] | None:
        rows = self.list_discovery_runs(1); return rows[0] if rows else None

    def new_since_latest_discovery(self) -> int:
        latest = self.latest_discovery_run()
        if not latest: return 0
        with self._connect() as connection:
            row = connection.execute("SELECT COUNT(*) count FROM jobs WHERE first_seen_at >= ?", (latest["started_at"],)).fetchone()
        return int(row["count"])
