from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from job_hunter.database import JobDatabase
from job_hunter.discovery.lock import DiscoveryAlreadyRunning, DiscoveryLock
from job_hunter.models import Job
from job_hunter.operations import generate_job_cv


def job(url: str, decision="APPLY", score=80, seen=None) -> Job:
    return Job("Data Analyst", "Example", "Argentina", "Remote", "SQL Power BI analytics", "test", url,
               discovered_at=seen or datetime.now(timezone.utc).isoformat(timespec="seconds"), score=score,
               decision=decision, reasons={"matched_skills": ["sql"], "missing_skills": [],
               "hard_reject_reasons": [], "positive_reasons": ["Role match"]})


def test_new_is_default_and_tracking_survives_rediscovery(tmp_path):
    database = JobDatabase(tmp_path / "jobs.db")
    first, second = "2026-08-29T10:00:00+00:00", "2026-08-29T18:00:00+00:00"
    assert database.upsert(job("https://example.test/1", seen=first))
    row = database.list_jobs()[0]; database.set_application_status(row["id"], "SHORTLISTED")
    assert not database.upsert(job("https://example.test/1", score=82, seen=second))
    refreshed = database.list_jobs()[0]
    assert refreshed["application_status"] == "SHORTLISTED"
    assert refreshed["first_seen_at"] == first
    assert refreshed["last_seen_at"] == second
    assert refreshed["last_scored_at"] == second


def test_application_status_new_by_default(tmp_path):
    database = JobDatabase(tmp_path / "jobs.db"); database.upsert(job("https://example.test/new"))
    assert database.list_jobs()[0]["application_status"] == "NEW"


def test_cv_generated_and_applied_timestamps(tmp_path):
    database = JobDatabase(tmp_path / "jobs.db"); database.upsert(job("https://example.test/cv"))
    job_id = database.list_jobs()[0]["id"]
    output, adapted = generate_job_cv(database.path, job_id, output_root=tmp_path / "outputs")
    assert output.exists() and adapted.validation_status == "VALID"
    row = database.get_job_row(job_id); assert row["application_status"] == "CV_GENERATED" and row["cv_generated_at"]
    database.set_application_status(job_id, "APPROVED_TO_APPLY")
    database.set_application_status(job_id, "APPLIED")
    row = database.get_job_row(job_id); assert row["application_status"] == "APPLIED" and row["applied_at"]


def test_reject_cannot_generate_cv_without_override(tmp_path):
    database = JobDatabase(tmp_path / "jobs.db"); database.upsert(job("https://example.test/reject", "REJECT", 20))
    with pytest.raises(ValueError): generate_job_cv(database.path, database.list_jobs()[0]["id"], output_root=tmp_path / "outputs")


def test_skipped_is_not_recommended(tmp_path):
    database = JobDatabase(tmp_path / "jobs.db"); database.upsert(job("https://example.test/skip"))
    database.set_application_status(database.list_jobs()[0]["id"], "SKIPPED")
    assert database.list_jobs("recommended") == []
    assert len(database.list_jobs("discarded")) == 1


def test_today_and_apply_filters(tmp_path):
    database = JobDatabase(tmp_path / "jobs.db")
    database.upsert(job("https://example.test/today"))
    old = (datetime.now(timezone.utc) - timedelta(days=2)).isoformat(timespec="seconds")
    database.upsert(job("https://example.test/old", "REVIEW", 65, old))
    assert [row["url"] for row in database.list_jobs("today")] == ["https://example.test/today"]
    assert [row["decision"] for row in database.list_jobs("recommended")] == ["APPLY"]
    assert [row["decision"] for row in database.list_jobs("review")] == ["REVIEW"]


def test_discovery_runs_are_persisted(tmp_path):
    database = JobDatabase(tmp_path / "jobs.db"); run_id = database.create_discovery_run(["mock"])
    database.finish_discovery_run(run_id, status="COMPLETED", preliminary=5, new_jobs=2, updated_jobs=1, duplicates=2, apply_count=1)
    run = database.latest_discovery_run()
    assert run["status"] == "COMPLETED" and run["new_jobs"] == 2 and run["finished_at"]


def test_discovery_lock_prevents_concurrency_and_cleans_up(tmp_path):
    path = tmp_path / "discovery.lock"
    with DiscoveryLock(path):
        with pytest.raises(DiscoveryAlreadyRunning):
            with DiscoveryLock(path): pass
    assert not path.exists()


def test_scheduler_scripts_have_required_times_and_recovery_settings():
    installer = Path("scripts/install_windows_tasks.ps1").read_text(encoding="utf-8")
    runner = Path("scripts/run_discovery.ps1").read_text(encoding="utf-8")
    assert all(value in installer for value in ("08:00", "18:00", "StartWhenAvailable", "IgnoreNew"))
    assert "discovery.lock" not in runner  # Lock ownership stays in the Python CLI.
    assert "logs\\discovery" in runner


def test_private_and_logs_are_ignored():
    ignore = Path(".gitignore").read_text(encoding="utf-8")
    assert "private/" in ignore and "logs/*" in ignore and "data/discovery.lock" in ignore


def test_legacy_database_migrates_without_losing_row(tmp_path):
    path = tmp_path / "legacy.db"
    with sqlite3.connect(path) as connection:
        connection.execute("""CREATE TABLE jobs (id INTEGER PRIMARY KEY, title TEXT, company TEXT, location TEXT,
            work_mode TEXT, description TEXT, source TEXT, url TEXT UNIQUE, score REAL, decision TEXT, reasons TEXT,
            created_at TEXT)""")
        connection.execute("INSERT INTO jobs VALUES (1,'A','B','C','Remote','D','x','u',80,'APPLY','{}','2026-01-01T00:00:00+00:00')")
    database = JobDatabase(path); row = database.list_jobs()[0]
    assert row["id"] == 1 and row["application_status"] == "NEW" and row["first_seen_at"] == row["created_at"]
