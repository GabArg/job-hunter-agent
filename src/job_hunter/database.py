from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from .models import Job

APPLICATION_STATUSES = {"NEW", "SHORTLISTED", "CV_GENERATED", "APPROVED_TO_APPLY", "APPLIED", "SKIPPED"}
APPLICATION_STAGES = {
    "NOT_APPLIED", "APPLIED", "RECRUITER_VIEWED", "RECRUITER_CONTACT", "HR_INTERVIEW",
    "TECH_INTERVIEW", "BUSINESS_INTERVIEW", "FINAL_INTERVIEW", "ASSESSMENT", "OFFER", "HIRED",
    "REJECTED", "WITHDRAWN", "CLOSED_NO_RESPONSE",
}

JOBS_SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT NOT NULL, company TEXT NOT NULL,
    location TEXT NOT NULL, work_mode TEXT NOT NULL, description TEXT NOT NULL,
    source TEXT NOT NULL, url TEXT NOT NULL UNIQUE, published_at TEXT,
    discovered_at TEXT NOT NULL, score REAL NOT NULL,
    decision TEXT NOT NULL CHECK (decision IN ('APPLY', 'REVIEW', 'REJECT')),
    reasons TEXT NOT NULL, created_at TEXT NOT NULL,
    application_status TEXT NOT NULL DEFAULT 'NEW', first_seen_at TEXT,
    last_seen_at TEXT, last_scored_at TEXT, cv_generated_at TEXT, applied_at TEXT,
    cv_pdf_path TEXT, cv_pdf_status TEXT NOT NULL DEFAULT 'PDF_NOT_GENERATED',
    cv_pdf_generated_at TEXT, cv_pdf_pages INTEGER,
    application_method TEXT NOT NULL DEFAULT 'UNKNOWN', application_email TEXT,
    application_url TEXT, application_instructions TEXT NOT NULL DEFAULT '[]',
    email_subject TEXT, email_body TEXT,
    email_draft_status TEXT NOT NULL DEFAULT 'NOT_GENERATED', email_sent_at TEXT,
    email_message_id TEXT, selected_application_channel TEXT, application_channel_used TEXT,
    gmail_draft_id TEXT, gmail_message_id TEXT, gmail_draft_created_at TEXT, gmail_account_email TEXT
    ,application_stage TEXT NOT NULL DEFAULT 'NOT_APPLIED', stage_updated_at TEXT,
    last_contact_at TEXT, next_action_at TEXT, next_action_note TEXT,
    rejection_reason TEXT, offer_notes TEXT
)
"""
APPLICATION_STAGE_HISTORY_SCHEMA = """
CREATE TABLE IF NOT EXISTS application_stage_history (
 id INTEGER PRIMARY KEY AUTOINCREMENT, job_id INTEGER NOT NULL,
 from_stage TEXT NOT NULL, to_stage TEXT NOT NULL, changed_at TEXT NOT NULL,
 note TEXT, source TEXT NOT NULL CHECK (source IN ('MANUAL','SYSTEM')),
 FOREIGN KEY(job_id) REFERENCES jobs(id)
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
SOURCE_METRICS_SCHEMA = """
CREATE TABLE IF NOT EXISTS source_metrics (
 id INTEGER PRIMARY KEY AUTOINCREMENT, run_id INTEGER, source TEXT NOT NULL, target TEXT,
 sector TEXT NOT NULL DEFAULT 'Other', recorded_at TEXT NOT NULL, fetched INTEGER DEFAULT 0,
 relevant_by_title INTEGER DEFAULT 0, relevant_after_description INTEGER DEFAULT 0,
 pre_score_rejected INTEGER DEFAULT 0, scored INTEGER DEFAULT 0, apply_count INTEGER DEFAULT 0,
 review_count INTEGER DEFAULT 0, reject_count INTEGER DEFAULT 0, duplicates INTEGER DEFAULT 0,
 errors INTEGER DEFAULT 0, error_message TEXT, latency_ms INTEGER DEFAULT 0, fresh_count INTEGER DEFAULT 0,
 quality_score REAL DEFAULT 0, consecutive_failures INTEGER DEFAULT 0, health TEXT DEFAULT 'HEALTHY'
)
"""
GMAIL_AUDIT_SCHEMA = """
CREATE TABLE IF NOT EXISTS gmail_audit (
 id INTEGER PRIMARY KEY AUTOINCREMENT, timestamp TEXT NOT NULL, job_id INTEGER,
 action TEXT NOT NULL, recipient TEXT, draft_id TEXT, account_email TEXT,
 status TEXT NOT NULL, error TEXT
)
"""
IMPORT_HISTORY_SCHEMA = """
CREATE TABLE IF NOT EXISTS import_history (
 id INTEGER PRIMARY KEY AUTOINCREMENT, imported_at TEXT NOT NULL, source_url TEXT,
 company TEXT, title TEXT, source_type TEXT NOT NULL, result TEXT NOT NULL,
 job_id INTEGER, duplicate_job_id INTEGER, warnings TEXT NOT NULL DEFAULT '[]', import_method TEXT NOT NULL
)
"""


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _clean_note(value: str | None) -> str | None:
    cleaned = " ".join(str(value or "").split()).strip()
    return cleaned[:2_000] or None


class JobDatabase:
    def __init__(self, path: str | Path):
        self.path = Path(path); self.path.parent.mkdir(parents=True, exist_ok=True); self._initialize()

    @contextmanager
    def _connect(self):
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.execute(JOBS_SCHEMA); connection.execute(RUNS_SCHEMA); connection.execute(SOURCE_METRICS_SCHEMA); connection.execute(IMPORT_HISTORY_SCHEMA); connection.execute(GMAIL_AUDIT_SCHEMA); connection.execute(APPLICATION_STAGE_HISTORY_SCHEMA)
            columns = {row[1] for row in connection.execute("PRAGMA table_info(jobs)")}
            migrations = {
                "published_at": "TEXT", "discovered_at": "TEXT", "application_status": "TEXT NOT NULL DEFAULT 'NEW'",
                "first_seen_at": "TEXT", "last_seen_at": "TEXT", "last_scored_at": "TEXT",
                "cv_generated_at": "TEXT", "applied_at": "TEXT",
                "cv_pdf_path": "TEXT", "cv_pdf_status": "TEXT NOT NULL DEFAULT 'PDF_NOT_GENERATED'",
                "cv_pdf_generated_at": "TEXT", "cv_pdf_pages": "INTEGER",
                "gmail_draft_id": "TEXT", "gmail_message_id": "TEXT",
                "gmail_draft_created_at": "TEXT", "gmail_account_email": "TEXT",
                "application_method": "TEXT NOT NULL DEFAULT 'UNKNOWN'", "application_email": "TEXT",
                "application_url": "TEXT", "application_instructions": "TEXT NOT NULL DEFAULT '[]'",
                "email_subject": "TEXT", "email_body": "TEXT",
                "email_draft_status": "TEXT NOT NULL DEFAULT 'NOT_GENERATED'", "email_sent_at": "TEXT",
                "email_message_id": "TEXT", "selected_application_channel": "TEXT", "application_channel_used": "TEXT",
                "sector": "TEXT NOT NULL DEFAULT 'Other'", "sector_confidence": "REAL NOT NULL DEFAULT 0",
                "priority_fresh": "INTEGER NOT NULL DEFAULT 0",
                "imported_manually": "INTEGER NOT NULL DEFAULT 0", "imported_at": "TEXT",
                "import_source_url": "TEXT", "import_method": "TEXT",
                "application_stage": "TEXT NOT NULL DEFAULT 'NOT_APPLIED'", "stage_updated_at": "TEXT",
                "last_contact_at": "TEXT", "next_action_at": "TEXT", "next_action_note": "TEXT",
                "rejection_reason": "TEXT", "offer_notes": "TEXT",
            }
            for name, definition in migrations.items():
                if name not in columns: connection.execute(f"ALTER TABLE jobs ADD COLUMN {name} {definition}")
            connection.execute("UPDATE jobs SET discovered_at = COALESCE(discovered_at, created_at)")
            connection.execute("UPDATE jobs SET application_status = COALESCE(application_status, 'NEW')")
            connection.execute("UPDATE jobs SET first_seen_at = COALESCE(first_seen_at, discovered_at, created_at)")
            connection.execute("UPDATE jobs SET last_seen_at = COALESCE(last_seen_at, discovered_at, created_at)")
            connection.execute("UPDATE jobs SET last_scored_at = COALESCE(last_scored_at, discovered_at, created_at)")
            connection.execute("UPDATE jobs SET application_method = COALESCE(application_method, 'UNKNOWN')")
            connection.execute("UPDATE jobs SET application_instructions = COALESCE(application_instructions, '[]')")
            connection.execute("UPDATE jobs SET email_draft_status = COALESCE(email_draft_status, 'NOT_GENERATED')")
            connection.execute("""UPDATE jobs SET application_stage=CASE
                WHEN application_status='APPLIED' THEN 'APPLIED' ELSE 'NOT_APPLIED' END
                WHERE application_stage IS NULL OR application_stage='' OR
                (application_stage='NOT_APPLIED' AND application_status='APPLIED')""")
            from .application.detector import detect_application_channel
            for row in connection.execute("SELECT id,description,url FROM jobs WHERE application_method='UNKNOWN'").fetchall():
                detected = detect_application_channel(row["description"], row["url"])
                connection.execute("""UPDATE jobs SET application_method=?,application_email=?,application_url=?,
                    application_instructions=?,email_subject=? WHERE id=?""",
                    (detected.method.value, detected.email, detected.application_url,
                     json.dumps(detected.instructions, ensure_ascii=False), detected.required_subject, row["id"]))

    def upsert(self, job: Job) -> bool:
        if job.application_method == "UNKNOWN":
            from .application.detector import detect_application_channel
            detected = detect_application_channel(job.description, job.url, job.raw_data)
            job.application_method, job.application_email = detected.method.value, detected.email
            job.application_url, job.application_instructions = detected.application_url, detected.instructions
            job.email_subject = detected.required_subject
        seen_at = job.discovered_at or utc_now()
        values = (job.title, job.company, job.location, job.work_mode, job.description, job.source, job.url,
                  job.published_at, seen_at, job.score, job.decision, json.dumps(job.reasons, ensure_ascii=False),
                  job.created_at, seen_at, seen_at, seen_at, job.application_method, job.application_email,
                  job.application_url, json.dumps(job.application_instructions, ensure_ascii=False), job.email_subject,
                  job.sector, job.sector_confidence, int(job.priority_fresh), int(job.imported_manually),
                  job.imported_at, job.import_source_url, job.import_method)
        with self._connect() as connection:
            existed = connection.execute("SELECT 1 FROM jobs WHERE url = ?", (job.url,)).fetchone()
            connection.execute("""
                INSERT INTO jobs (title, company, location, work_mode, description, source, url, published_at,
                    discovered_at, score, decision, reasons, created_at, first_seen_at, last_seen_at, last_scored_at,
                    application_method, application_email, application_url, application_instructions, email_subject,
                    sector, sector_confidence, priority_fresh, imported_manually, imported_at, import_source_url, import_method)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(url) DO UPDATE SET
                    title=excluded.title, company=excluded.company, location=excluded.location,
                    work_mode=excluded.work_mode, description=excluded.description, source=excluded.source,
                    published_at=excluded.published_at, score=excluded.score, decision=excluded.decision,
                    reasons=excluded.reasons, last_seen_at=excluded.last_seen_at,
                    last_scored_at=excluded.last_scored_at, application_method=excluded.application_method,
                    application_email=excluded.application_email, application_url=excluded.application_url,
                    application_instructions=excluded.application_instructions,
                    email_subject=CASE WHEN jobs.email_draft_status='NOT_GENERATED' THEN excluded.email_subject ELSE jobs.email_subject END,
                    sector=excluded.sector,sector_confidence=excluded.sector_confidence,
                    priority_fresh=excluded.priority_fresh,
                    imported_manually=CASE WHEN jobs.imported_manually=1 THEN 1 ELSE excluded.imported_manually END,
                    imported_at=COALESCE(jobs.imported_at,excluded.imported_at),
                    import_source_url=COALESCE(jobs.import_source_url,excluded.import_source_url),
                    import_method=COALESCE(jobs.import_method,excluded.import_method)
            """, values)
        return existed is None

    def list_jobs(self, view: str | None = None, sector: str | None = None) -> list[dict[str, Any]]:
        clauses = {
            "today": "date(first_seen_at, 'localtime') = date('now', 'localtime')",
            "recommended": "decision = 'APPLY' AND application_status NOT IN ('APPLIED','SKIPPED')",
            "review": "decision = 'REVIEW' AND application_status NOT IN ('APPLIED','SKIPPED')",
            "cvs": "application_status = 'CV_GENERATED'",
            "applied": "application_status = 'APPLIED'",
            "discarded": "decision = 'REJECT' OR application_status = 'SKIPPED'",
        }
        conditions = [clauses[view]] if view in clauses else []
        values: list[Any] = []
        if sector and sector != "All": conditions.append("sector = ?"); values.append(sector)
        where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        with self._connect() as connection:
            rows = connection.execute(f"""SELECT * FROM jobs {where} ORDER BY
                CASE decision WHEN 'APPLY' THEN 0 WHEN 'REVIEW' THEN 1 ELSE 2 END,
                priority_fresh DESC, score DESC, COALESCE(published_at, '') DESC, id DESC""", values).fetchall()
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
                   decision=data["decision"], reasons=json.loads(data["reasons"]), created_at=data["created_at"],
                   application_method=data.get("application_method") or "UNKNOWN", application_email=data.get("application_email"),
                   application_url=data.get("application_url"), application_instructions=json.loads(data.get("application_instructions") or "[]"),
                   email_subject=data.get("email_subject"), email_body=data.get("email_body"),
                   email_draft_status=data.get("email_draft_status") or "NOT_GENERATED", email_sent_at=data.get("email_sent_at"),
                   email_message_id=data.get("email_message_id"), selected_application_channel=data.get("selected_application_channel"),
                   application_channel_used=data.get("application_channel_used"), sector=data.get("sector") or "Other",
                   sector_confidence=float(data.get("sector_confidence") or 0), priority_fresh=bool(data.get("priority_fresh")),
                   imported_manually=bool(data.get("imported_manually")), imported_at=data.get("imported_at"),
                   import_source_url=data.get("import_source_url"), import_method=data.get("import_method"))

    def select_application_channel(self, job_id: int, channel: str) -> None:
        if channel not in {"LINK", "EMAIL"}: raise ValueError("Channel must be LINK or EMAIL")
        row = self.get_job_row(job_id)
        if row is None: raise KeyError(f"Job not found: {job_id}")
        allowed = {"LINK": {"LINK"}, "EMAIL": {"EMAIL"}, "LINK_EMAIL": {"LINK", "EMAIL"}, "UNKNOWN": set()}[row["application_method"]]
        if channel not in allowed: raise ValueError(f"{channel} is not available for this job")
        with self._connect() as connection: connection.execute("UPDATE jobs SET selected_application_channel=? WHERE id=?", (channel, job_id))

    def save_email_draft(self, job_id: int, recipient: str, subject: str, body: str, message_id: str | None = None) -> None:
        if not recipient or "@" not in recipient or not subject.strip() or not body.strip(): raise ValueError("Recipient, subject and body are required")
        row = self.get_job_row(job_id)
        if row is None: raise KeyError(f"Job not found: {job_id}")
        if row["email_draft_status"] == "SENT": raise ValueError("A SENT email cannot be edited")
        with self._connect() as connection:
            connection.execute("""UPDATE jobs SET application_email=?,email_subject=?,email_body=?,
                email_draft_status=CASE WHEN email_draft_status='GMAIL_DRAFT_CREATED'
                    THEN 'GMAIL_DRAFT_STALE' ELSE 'GENERATED' END,email_message_id=? WHERE id=?""",
                (recipient, subject, body, message_id, job_id))

    def approve_email_draft(self, job_id: int) -> None:
        row = self.get_job_row(job_id)
        if row is None: raise KeyError(f"Job not found: {job_id}")
        if row.get("cv_pdf_status") != "PDF_VALID":
            raise ValueError("A VALID PDF CV is required before approving an email")
        with self._connect() as connection:
            cursor = connection.execute("UPDATE jobs SET email_draft_status='APPROVED' WHERE id=? AND email_draft_status='GENERATED'", (job_id,))
            if cursor.rowcount != 1: raise ValueError("Only a GENERATED email can be approved")

    def set_cv_pdf_result(self, job_id: int, path: str | Path, status: str, pages: int,
                          at: str | None = None) -> None:
        allowed = {"PDF_NOT_GENERATED", "PDF_GENERATED", "PDF_VALID", "PDF_INVALID", "TOO_LONG"}
        if status not in allowed: raise ValueError(f"Invalid PDF status: {status}")
        with self._connect() as connection:
            cursor = connection.execute("""UPDATE jobs SET cv_pdf_path=?,cv_pdf_status=?,
                cv_pdf_generated_at=?,cv_pdf_pages=?,email_draft_status=CASE
                    WHEN email_draft_status='GMAIL_DRAFT_CREATED' THEN 'GMAIL_DRAFT_STALE'
                    ELSE email_draft_status END WHERE id=?""",
                (str(path), status, at or utc_now(), int(pages), job_id))
            if cursor.rowcount != 1: raise KeyError(f"Job not found: {job_id}")

    def save_gmail_draft(self, job_id: int, draft_id: str, message_id: str | None,
                         account_email: str, at: str | None = None) -> None:
        timestamp = at or utc_now()
        with self._connect() as connection:
            cursor = connection.execute("""UPDATE jobs SET gmail_draft_id=?,gmail_message_id=?,
                gmail_draft_created_at=?,gmail_account_email=?,email_draft_status='GMAIL_DRAFT_CREATED'
                WHERE id=? AND email_draft_status='APPROVED' AND gmail_draft_id IS NULL""",
                (draft_id, message_id, timestamp, account_email, job_id))
            if cursor.rowcount != 1:
                raise ValueError("Email must be APPROVED and have no existing Gmail draft")

    def record_gmail_event(self, action: str, status: str, *, job_id: int | None = None,
                           recipient: str | None = None, draft_id: str | None = None,
                           account_email: str | None = None, error: str | None = None) -> None:
        from .application.email_sender import sanitize_gmail_error
        safe_error = sanitize_gmail_error(error) if error else None
        with self._connect() as connection:
            connection.execute("""INSERT INTO gmail_audit
                (timestamp,job_id,action,recipient,draft_id,account_email,status,error)
                VALUES (?,?,?,?,?,?,?,?)""", (utc_now(), job_id, action, recipient, draft_id,
                                                account_email, status, safe_error))

    def list_gmail_events(self, limit: int = 100) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute("SELECT * FROM gmail_audit ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
        return [dict(row) for row in rows]

    def latest_gmail_account(self) -> str | None:
        with self._connect() as connection:
            row = connection.execute("""SELECT account_email FROM gmail_audit
                WHERE account_email IS NOT NULL AND status='SUCCESS' ORDER BY id DESC LIMIT 1""").fetchone()
        return str(row["account_email"]) if row else None

    def mark_email_sent(self, job_id: int, message_id: str, channel: str = "EMAIL", at: str | None = None) -> None:
        timestamp = at or utc_now()
        with self._connect() as connection:
            cursor = connection.execute("""UPDATE jobs SET email_draft_status='SENT',email_sent_at=?,email_message_id=?,
                application_channel_used=? WHERE id=? AND email_draft_status='APPROVED'""",
                (timestamp, message_id, channel, job_id))
            if cursor.rowcount != 1: raise ValueError("Email must be APPROVED before marking SENT")

    def mark_link_applied(self, job_id: int, at: str | None = None) -> None:
        row = self.get_job_row(job_id)
        if row is None: raise KeyError(f"Job not found: {job_id}")
        if row["application_method"] not in {"LINK", "LINK_EMAIL"}: raise ValueError("LINK is not available")
        if row["application_method"] == "LINK_EMAIL" and row["selected_application_channel"] != "LINK": raise ValueError("Select LINK first")
        self.mark_applied(job_id, channel="LINK", at=at)

    def mark_applied(self, job_id: int, *, channel: str | None = None, at: str | None = None,
                     note: str | None = None, source: str = "MANUAL") -> None:
        if source not in {"MANUAL", "SYSTEM"}: raise ValueError("Invalid stage source")
        timestamp = at or utc_now()
        with self._connect() as connection:
            row = connection.execute("SELECT application_stage FROM jobs WHERE id=?", (job_id,)).fetchone()
            if row is None: raise KeyError(f"Job not found: {job_id}")
            previous = row["application_stage"] or "NOT_APPLIED"
            connection.execute("""UPDATE jobs SET application_status='APPLIED',application_stage='APPLIED',
                applied_at=COALESCE(applied_at,?),stage_updated_at=?,application_channel_used=COALESCE(?,application_channel_used)
                WHERE id=?""", (timestamp, timestamp, channel, job_id))
            if previous != "APPLIED":
                connection.execute("""INSERT INTO application_stage_history
                    (job_id,from_stage,to_stage,changed_at,note,source) VALUES (?,?,?,?,?,?)""",
                    (job_id, previous, "APPLIED", timestamp, _clean_note(note), source))

    def set_application_stage(self, job_id: int, stage: str, *, note: str | None = None,
                              at: str | None = None, source: str = "MANUAL") -> None:
        if stage not in APPLICATION_STAGES: raise ValueError(f"Invalid application stage: {stage}")
        if source not in {"MANUAL", "SYSTEM"}: raise ValueError("Invalid stage source")
        timestamp = at or utc_now()
        with self._connect() as connection:
            row = connection.execute("SELECT application_stage,application_status FROM jobs WHERE id=?", (job_id,)).fetchone()
            if row is None: raise KeyError(f"Job not found: {job_id}")
            previous = row["application_stage"] or "NOT_APPLIED"
            if previous == stage: raise ValueError("Application stage is already set")
            applied = stage != "NOT_APPLIED"
            contact = stage not in {"NOT_APPLIED", "APPLIED", "RECRUITER_VIEWED"}
            connection.execute("""UPDATE jobs SET application_stage=?,stage_updated_at=?,
                application_status=CASE WHEN ? THEN 'APPLIED' ELSE application_status END,
                applied_at=CASE WHEN ? THEN COALESCE(applied_at,?) ELSE applied_at END,
                last_contact_at=CASE WHEN ? THEN ? ELSE last_contact_at END,
                rejection_reason=CASE WHEN ?='REJECTED' AND ? IS NOT NULL THEN ? ELSE rejection_reason END,
                offer_notes=CASE WHEN ?='OFFER' AND ? IS NOT NULL THEN ? ELSE offer_notes END WHERE id=?""",
                (stage, timestamp, applied, applied, timestamp, contact, timestamp,
                 stage, _clean_note(note), _clean_note(note), stage, _clean_note(note), _clean_note(note), job_id))
            connection.execute("""INSERT INTO application_stage_history
                (job_id,from_stage,to_stage,changed_at,note,source) VALUES (?,?,?,?,?,?)""",
                (job_id, previous, stage, timestamp, _clean_note(note), source))

    def set_next_action(self, job_id: int, at: str | None, note: str | None) -> None:
        if at and not (note or "").strip(): raise ValueError("Next action note is required with a date")
        with self._connect() as connection:
            cursor = connection.execute("UPDATE jobs SET next_action_at=?,next_action_note=? WHERE id=?",
                                        (at or None, _clean_note(note), job_id))
            if cursor.rowcount != 1: raise KeyError(f"Job not found: {job_id}")

    def application_history(self, job_id: int) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute("""SELECT * FROM application_stage_history
                WHERE job_id=? ORDER BY changed_at,id""", (job_id,)).fetchall()
        return [dict(row) for row in rows]

    def tracking_jobs(self) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute("""SELECT * FROM jobs WHERE application_stage!='NOT_APPLIED'
                OR application_status='APPLIED' ORDER BY COALESCE(stage_updated_at,applied_at) DESC,id DESC""").fetchall()
        return [dict(row) for row in rows]

    def set_application_status(self, job_id: int, status: str, at: str | None = None) -> None:
        if status not in APPLICATION_STATUSES: raise ValueError(f"Invalid application status: {status}")
        if status == "APPLIED":
            self.mark_applied(job_id, at=at)
            return
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
        counts = {key: int(row[key] or 0) for key in row.keys()}
        from .origin import origin_summary
        origin = origin_summary(self.list_jobs())
        counts.update({"discovered_today": origin["automatic_today"], "imported_today": origin["manual_today"],
                       "imported_week": origin["manual_week"]})
        return counts

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

    def latest_discovery_jobs(self) -> list[dict[str, Any]]:
        from .origin import jobs_created_by_run
        return jobs_created_by_run(self.list_jobs(), self.latest_discovery_run())

    def new_since_latest_discovery(self) -> int:
        return len(self.latest_discovery_jobs())

    def record_source_metric(self, *, run_id: int | None, source: str, target: str | None, sector: str,
                             fetched: int, relevant_by_title: int, relevant_after_description: int,
                             pre_score_rejected: int, scored: int, apply_count: int, review_count: int,
                             reject_count: int, duplicates: int, error: str | None, latency_ms: int,
                             fresh_count: int, quality_score: float) -> None:
        with self._connect() as connection:
            previous = connection.execute("SELECT consecutive_failures FROM source_metrics WHERE source=? ORDER BY id DESC LIMIT 1", (source,)).fetchone()
            failures = (int(previous[0]) + 1 if previous else 1) if error else 0
            health = "DEGRADED" if failures >= 3 else "HEALTHY"
            connection.execute("""INSERT INTO source_metrics (run_id,source,target,sector,recorded_at,fetched,
                relevant_by_title,relevant_after_description,pre_score_rejected,scored,apply_count,review_count,
                reject_count,duplicates,errors,error_message,latency_ms,fresh_count,quality_score,consecutive_failures,health)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (run_id,source,target,sector,utc_now(),fetched,relevant_by_title,relevant_after_description,
                 pre_score_rejected,scored,apply_count,review_count,reject_count,duplicates,int(bool(error)),error,
                 latency_ms,fresh_count,quality_score,failures,health))

    def source_intelligence(self, sector: str | None = None) -> list[dict[str, Any]]:
        condition, values = ("WHERE sector=?", [sector]) if sector and sector != "All" else ("", [])
        query = f"""SELECT source,target,sector,SUM(fetched) fetched,SUM(relevant_after_description) relevant,
            SUM(apply_count) apply_count,SUM(review_count) review_count,SUM(reject_count) reject_count,
            SUM(duplicates) duplicates,SUM(errors) errors,ROUND(AVG(quality_score),2) quality_score,
            MAX(recorded_at) last_run,
            (SELECT health FROM source_metrics recent WHERE recent.source=source_metrics.source ORDER BY id DESC LIMIT 1) health
            FROM source_metrics {condition} GROUP BY source,target,sector ORDER BY quality_score DESC"""
        with self._connect() as connection: rows = connection.execute(query, values).fetchall()
        return [dict(row) for row in rows]

    def discovery_report(self) -> dict[str, Any]:
        intelligence = self.source_intelligence(); week_ago = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat(timespec="seconds")
        with self._connect() as connection:
            decisions = connection.execute("SELECT decision,COUNT(*) count FROM jobs WHERE first_seen_at>=? GROUP BY decision", (week_ago,)).fetchall()
        return {"sources": intelligence, "jobs_last_7_days": sum(row["count"] for row in decisions),
                "decisions": {row["decision"]: row["count"] for row in decisions},
                "targets_without_results": [row["target"] for row in intelligence if row["fetched"] == 0],
                "frequent_errors": [row["source"] for row in intelligence if row["errors"] > 0]}

    def create_backup(self, directory: str | Path | None = None) -> Path:
        destination_dir = Path(directory or self.path.parent / "backups")
        destination_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        destination = destination_dir / f"{self.path.stem}_{timestamp}{self.path.suffix}"
        source = sqlite3.connect(self.path)
        target = sqlite3.connect(destination)
        try:
            source.backup(target)
        finally:
            target.close(); source.close()
        return destination

    def cleanup_old_jobs(self, max_age_days: int, *, apply: bool = False,
                         now: datetime | None = None) -> dict[str, Any]:
        from .discovery.matching import parse_datetime
        reference = now or datetime.now(timezone.utc)
        threshold = reference - timedelta(days=max_age_days)
        eligible: list[dict[str, Any]] = []
        protected: list[dict[str, Any]] = []
        with self._connect() as connection:
            rows = connection.execute("""SELECT id,company,title,published_at,decision,application_status
                FROM jobs WHERE published_at IS NOT NULL ORDER BY id""").fetchall()
            for row in rows:
                published = parse_datetime(row["published_at"])
                if published is None or published >= threshold:
                    continue
                data = dict(row)
                if row["application_status"] in {"NEW", "SKIPPED"}:
                    eligible.append(data)
                else:
                    data["reason"] = "PROTECTED_OLD_JOB"
                    protected.append(data)
            backup = None
            if apply and eligible:
                backup = self.create_backup()
                connection.executemany("DELETE FROM jobs WHERE id=?", [(row["id"],) for row in eligible])
        return {"threshold": threshold.isoformat(timespec="seconds"), "eligible": eligible,
                "protected": protected, "deleted": len(eligible) if apply else 0,
                "backup": str(backup) if backup else None}

    def repair_invalid_work_modes(self, *, apply: bool = False) -> list[dict[str, Any]]:
        from .normalizer import VALID_WORK_MODES, normalize_work_mode
        changes: list[dict[str, Any]] = []
        with self._connect() as connection:
            rows = connection.execute("SELECT id,company,title,work_mode,description FROM jobs ORDER BY id").fetchall()
            for row in rows:
                before = str(row["work_mode"] or "")
                if before.casefold() in VALID_WORK_MODES:
                    continue
                after = normalize_work_mode(before, str(row["description"] or ""))
                changes.append({"job_id": row["id"], "company": row["company"], "title": row["title"],
                                "before": before, "after": after})
                if apply:
                    connection.execute("UPDATE jobs SET work_mode=? WHERE id=?", (after, row["id"]))
        return changes

    def enrich_job_sectors(self, *, manual_only: bool = False, apply: bool = False) -> dict[str, Any]:
        """Reclassify sectors without touching scoring, decisions, or operational state."""
        from .discovery.target_registry import detect_sector

        where = "WHERE imported_manually=1" if manual_only else ""
        changes: list[dict[str, Any]] = []
        with self._connect() as connection:
            rows = connection.execute(
                f"""SELECT id,company,title,description,sector,sector_confidence,score,decision,
                    application_status FROM jobs {where} ORDER BY id"""
            ).fetchall()
            for row in rows:
                after, confidence = detect_sector(row["company"], row["description"], row["title"])
                before = row["sector"] or "Other"
                before_confidence = float(row["sector_confidence"] or 0)
                if confidence <= before_confidence or (after == "Other" and before != "Other"):
                    continue
                changes.append({
                    "job_id": row["id"], "company": row["company"], "title": row["title"],
                    "sector_before": before, "sector_after": after,
                    "confidence_before": before_confidence, "confidence_after": confidence,
                    "score": row["score"], "decision": row["decision"],
                    "application_status": row["application_status"],
                })
        backup = self.create_backup() if apply and changes else None
        if apply and changes:
            with self._connect() as connection:
                connection.executemany(
                    "UPDATE jobs SET sector=?,sector_confidence=? WHERE id=?",
                    [(row["sector_after"], row["confidence_after"], row["job_id"]) for row in changes],
                )
        return {"changes": changes, "updated": len(changes) if apply else 0,
                "backup": str(backup) if backup else None}

    def find_duplicate_job(self, job: Job, original_url: str | None = None) -> dict[str, Any] | None:
        from .discovery.aggregator import canonical_url, job_fingerprint
        canonical = canonical_url(job.url)
        original = canonical_url(original_url or "")
        with self._connect() as connection:
            rows = connection.execute("SELECT * FROM jobs ORDER BY id").fetchall()
        for row in rows:
            row_url = canonical_url(str(row["url"] or ""))
            if row_url and row_url in {canonical, original}:
                return dict(row)
        candidate_key = tuple(str(value or "").strip().casefold() for value in (job.company, job.title, job.location))
        candidate_fingerprint = job_fingerprint(job)
        for row in rows:
            row_key = tuple(str(row[key] or "").strip().casefold() for key in ("company", "title", "location"))
            existing = Job(str(row["title"]), str(row["company"]), str(row["location"]), str(row["work_mode"]),
                           str(row["description"]), str(row["source"]), str(row["url"]))
            if row_key == candidate_key or job_fingerprint(existing) == candidate_fingerprint:
                return dict(row)
        return None

    def promote_manual_job_url(self, job_id: int, public_url: str) -> None:
        """Replace an internal manual key with a reviewed public URL without creating a row."""
        from .application.detector import detect_application_channel
        from .discovery.aggregator import canonical_url
        from .importer.url_importer import is_internal_job_url

        canonical = canonical_url(public_url)
        if not canonical.startswith(("http://", "https://")):
            raise ValueError("A public HTTP(S) URL is required")
        row = self.get_job_row(job_id)
        if row is None: raise KeyError(f"Job not found: {job_id}")
        if not is_internal_job_url(str(row["url"] or "")):
            return
        detection = detect_application_channel(str(row["description"] or ""), canonical)
        with self._connect() as connection:
            connection.execute("""UPDATE jobs SET url=?,import_source_url=?,application_method=?,
                application_email=?,application_url=?,application_instructions=?,email_subject=? WHERE id=?""",
                (canonical, canonical, detection.method.value, detection.email, detection.application_url,
                 json.dumps(detection.instructions, ensure_ascii=False), detection.required_subject, job_id))

    def record_import(self, *, source_url: str | None, company: str | None, title: str | None,
                      source_type: str, result: str, job_id: int | None = None,
                      duplicate_job_id: int | None = None, warnings: list[str] | None = None,
                      import_method: str = "PUBLIC_URL") -> None:
        with self._connect() as connection:
            connection.execute("""INSERT INTO import_history (imported_at,source_url,company,title,source_type,
                result,job_id,duplicate_job_id,warnings,import_method) VALUES (?,?,?,?,?,?,?,?,?,?)""",
                (utc_now(), source_url, company, title, source_type, result, job_id, duplicate_job_id,
                 json.dumps(warnings or [], ensure_ascii=False), import_method))

    def list_import_history(self, limit: int = 100) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute("SELECT * FROM import_history ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
        return [dict(row) for row in rows]
