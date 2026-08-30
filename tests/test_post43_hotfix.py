from __future__ import annotations

import sqlite3
from datetime import datetime, timezone

import pytest

from job_hunter.database import JobDatabase
from job_hunter.models import Job
from job_hunter.normalizer import VALID_WORK_MODES, _normalize_work_mode, normalize_job, normalize_work_mode


NOW = datetime(2026, 8, 30, 12, tzinfo=timezone.utc)


def stored_job(url: str, published_at: str | None, work_mode="unknown") -> Job:
    return Job("Data Analyst", "Example", "Argentina", work_mode, "Data analysis", "test", url,
               published_at=published_at, score=60, decision="REVIEW", reasons={})


@pytest.mark.parametrize("value,description,expected", [
    ({"id": "permanent", "label": "full-time"}, "", "unknown"),
    ("full-time", "", "unknown"),
    (None, "This is a fully remote role", "remote"),
    ([], "Modalidad híbrida", "hybrid"),
    ({"workplace": "on-site"}, "", "onsite"),
    (None, "Full-time analyst in Buenos Aires", "unknown"),
])
def test_defensive_work_mode_normalization(value, description, expected):
    result = normalize_work_mode(value, description)
    assert result == expected and isinstance(result, str) and result in VALID_WORK_MODES


def test_raw_dict_never_reaches_normalized_job():
    job = stored_job("https://x/dict", "2026-08-30", {"id": "permanent", "label": "full-time"})
    normalize_job(job)
    assert job.work_mode == "unknown" and isinstance(job.work_mode, str)


def test_cleanup_detects_old_but_not_null_or_unparseable(tmp_path):
    db = JobDatabase(tmp_path / "jobs.db")
    db.upsert(stored_job("https://x/old", "2026-07-01T00:00:00+00:00"))
    db.upsert(stored_job("https://x/null", None))
    db.upsert(stored_job("https://x/bad", "not-a-date"))
    result = db.cleanup_old_jobs(14, now=NOW)
    assert [row["title"] for row in result["eligible"]] == ["Data Analyst"]
    assert result["deleted"] == 0 and len(db.list_jobs()) == 3


@pytest.mark.parametrize("status", ["APPLIED", "CV_GENERATED", "APPROVED_TO_APPLY", "SHORTLISTED"])
def test_cleanup_protects_operational_jobs(tmp_path, status):
    db = JobDatabase(tmp_path / "jobs.db"); db.upsert(stored_job("https://x/" + status, "2026-06-01"))
    job_id = db.list_jobs()[0]["id"]; db.set_application_status(job_id, status)
    result = db.cleanup_old_jobs(14, apply=True, now=NOW)
    assert result["deleted"] == 0 and result["protected"][0]["reason"] == "PROTECTED_OLD_JOB"
    assert db.get_job_row(job_id) is not None


def test_cleanup_apply_deletes_only_eligible_and_creates_backup(tmp_path):
    db = JobDatabase(tmp_path / "jobs.db")
    db.upsert(stored_job("https://x/eligible", "2026-06-01"))
    db.upsert(stored_job("https://x/protected", "2026-06-01"))
    protected_id = next(row["id"] for row in db.list_jobs() if row["url"].endswith("protected"))
    db.set_application_status(protected_id, "APPLIED")
    result = db.cleanup_old_jobs(14, apply=True, now=NOW)
    assert result["deleted"] == 1 and result["backup"]
    assert len(db.list_jobs()) == 1 and db.list_jobs()[0]["id"] == protected_id


def test_existing_invalid_work_mode_repair_changes_no_other_fields(tmp_path):
    db = JobDatabase(tmp_path / "jobs.db"); db.upsert(stored_job("https://x/mode", "2026-08-30", "remote"))
    row = db.list_jobs()[0]
    with sqlite3.connect(db.path) as connection:
        connection.execute("UPDATE jobs SET work_mode=? WHERE id=?", ("{'label':'full-time'}", row["id"]))
    before = db.get_job_row(row["id"]); preview = db.repair_invalid_work_modes()
    assert preview[0]["after"] == "unknown" and db.get_job_row(row["id"])["work_mode"] == "{'label':'full-time'}"
    db.repair_invalid_work_modes(apply=True); after = db.get_job_row(row["id"])
    assert after["work_mode"] == "unknown"
    assert (after["score"], after["decision"], after["application_status"]) == (before["score"], before["decision"], before["application_status"])


def test_backward_compatibility_wrapper_returns_valid_string():
    assert _normalize_work_mode("remoto") == "remote"
