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

    def upsert(self, job: Job) -> bool:
        values = (
            job.title,
            job.company,
            job.location,
            job.work_mode,
            job.description,
            job.source,
            job.url,
            job.score,
            job.decision,
            json.dumps(job.reasons, ensure_ascii=False),
            job.created_at,
        )
        with self._connect() as connection:
            existed = connection.execute("SELECT 1 FROM jobs WHERE url = ?", (job.url,)).fetchone()
            connection.execute(
                """
                INSERT INTO jobs (title, company, location, work_mode, description, source, url, score, decision, reasons, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(url) DO UPDATE SET
                    title=excluded.title, company=excluded.company, location=excluded.location,
                    work_mode=excluded.work_mode, description=excluded.description, source=excluded.source,
                    score=excluded.score, decision=excluded.decision, reasons=excluded.reasons
                """,
                values,
            )
        return existed is None

    def list_jobs(self) -> list[dict[str, object]]:
        with self._connect() as connection:
            rows = connection.execute("SELECT * FROM jobs ORDER BY score DESC, id DESC").fetchall()
        return [dict(row) for row in rows]
