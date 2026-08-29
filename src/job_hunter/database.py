from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from .models import Job

SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    company TEXT NOT NULL,
    location TEXT NOT NULL,
    work_mode TEXT NOT NULL,
    description TEXT NOT NULL,
    source TEXT NOT NULL,
    url TEXT NOT NULL UNIQUE,
    published_at TEXT,
    discovered_at TEXT NOT NULL,
    score REAL NOT NULL,
    decision TEXT NOT NULL CHECK (decision IN ('APPLY', 'REVIEW', 'REJECT')),
    reasons TEXT NOT NULL,
    created_at TEXT NOT NULL
)
"""


class JobDatabase:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.execute(SCHEMA)
            columns = {row[1] for row in connection.execute("PRAGMA table_info(jobs)")}
            if "published_at" not in columns:
                connection.execute("ALTER TABLE jobs ADD COLUMN published_at TEXT")
            if "discovered_at" not in columns:
                connection.execute("ALTER TABLE jobs ADD COLUMN discovered_at TEXT")
                connection.execute("UPDATE jobs SET discovered_at = created_at WHERE discovered_at IS NULL")

    def upsert(self, job: Job) -> bool:
        values = (
            job.title,
            job.company,
            job.location,
            job.work_mode,
            job.description,
            job.source,
            job.url,
            job.published_at,
            job.discovered_at,
            job.score,
            job.decision,
            json.dumps(job.reasons, ensure_ascii=False),
            job.created_at,
        )
        with self._connect() as connection:
            existed = connection.execute("SELECT 1 FROM jobs WHERE url = ?", (job.url,)).fetchone()
            connection.execute(
                """
                INSERT INTO jobs (title, company, location, work_mode, description, source, url, published_at, discovered_at, score, decision, reasons, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(url) DO UPDATE SET
                    title=excluded.title, company=excluded.company, location=excluded.location,
                    work_mode=excluded.work_mode, description=excluded.description, source=excluded.source,
                    published_at=excluded.published_at, discovered_at=excluded.discovered_at,
                    score=excluded.score, decision=excluded.decision, reasons=excluded.reasons
                """,
                values,
            )
        return existed is None

    def list_jobs(self) -> list[dict[str, object]]:
        with self._connect() as connection:
            rows = connection.execute(
                """SELECT * FROM jobs ORDER BY
                CASE decision WHEN 'APPLY' THEN 0 WHEN 'REVIEW' THEN 1 ELSE 2 END,
                score DESC, COALESCE(published_at, '') DESC, id DESC"""
            ).fetchall()
        return [dict(row) for row in rows]

    def get_job(self, job_id: int | None = None, url: str | None = None) -> Job | None:
        if job_id is None and url is None:
            raise ValueError("job_id or url is required")
        query, value = ("id = ?", job_id) if job_id is not None else ("url = ?", url)
        with self._connect() as connection:
            row = connection.execute(f"SELECT * FROM jobs WHERE {query}", (value,)).fetchone()
        if row is None:
            return None
        data = dict(row)
        return Job(
            title=data["title"], company=data["company"], location=data["location"],
            work_mode=data["work_mode"], description=data["description"], source=data["source"],
            url=data["url"], published_at=data.get("published_at"),
            discovered_at=data.get("discovered_at") or data["created_at"], id=data["id"],
            score=data["score"], decision=data["decision"], reasons=json.loads(data["reasons"]),
            created_at=data["created_at"],
        )
