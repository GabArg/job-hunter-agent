from __future__ import annotations

import sqlite3
import sys
from datetime import datetime, timezone

import pytest

from job_hunter.database import APPLICATION_STAGES, JobDatabase
from job_hunter.cli import main
from job_hunter.models import Job
from job_hunter.tracking import analytics_snapshot, no_response_band


def job(number: int, title: str = "Data Analyst", source: str = "linkedin", score: float = 80) -> Job:
    return Job(title, f"Example {number}", "Argentina", "remote", "SQL Power BI", source,
               f"https://example.test/{number}", score=score, decision="APPLY", reasons={})


def stored(database: JobDatabase, number: int, **kwargs) -> int:
    database.upsert(job(number, **kwargs)); return int(next(row["id"] for row in database.list_jobs() if row["url"].endswith(f"/{number}")))


def test_manual_applied_creates_stage_timestamp_and_history(tmp_path):
    database = JobDatabase(tmp_path / "jobs.db"); job_id = stored(database, 1)
    database.mark_applied(job_id, channel="LINK", at="2026-08-30T12:00:00+00:00", note="Postulación confirmada")
    row = database.get_job_row(job_id); history = database.application_history(job_id)
    assert row["application_status"] == row["application_stage"] == "APPLIED"
    assert row["applied_at"] == row["stage_updated_at"] == "2026-08-30T12:00:00+00:00"
    assert history[0]["from_stage"] == "NOT_APPLIED" and history[0]["to_stage"] == "APPLIED"
    assert history[0]["note"] == "Postulación confirmada" and history[0]["source"] == "MANUAL"


def test_stage_changes_append_history_notes_without_changing_score_or_decision(tmp_path):
    database = JobDatabase(tmp_path / "jobs.db"); job_id = stored(database, 2)
    database.mark_applied(job_id, at="2026-08-30T12:00:00+00:00"); before = database.get_job_row(job_id)
    database.set_application_stage(job_id, "HR_INTERVIEW", note="Entrevista ficticia", at="2026-09-05T12:00:00+00:00")
    database.set_application_stage(job_id, "RECRUITER_CONTACT", note="Corrección", at="2026-09-05T13:00:00+00:00")
    after = database.get_job_row(job_id); history = database.application_history(job_id)
    assert (after["score"], after["decision"]) == (before["score"], before["decision"])
    assert [(event["from_stage"], event["to_stage"]) for event in history][-2:] == [
        ("APPLIED", "HR_INTERVIEW"), ("HR_INTERVIEW", "RECRUITER_CONTACT")]
    assert after["last_contact_at"] == "2026-09-05T13:00:00+00:00"


def test_closed_no_response_and_next_action_are_explicit(tmp_path):
    database = JobDatabase(tmp_path / "jobs.db"); job_id = stored(database, 3)
    database.mark_applied(job_id, at="2026-08-20T12:00:00+00:00")
    database.set_next_action(job_id, "2026-09-03T12:00:00+00:00", "Hacer follow-up")
    assert database.get_job_row(job_id)["next_action_note"] == "Hacer follow-up"
    assert no_response_band("APPLIED", 10) == "10+ días"
    database.set_application_stage(job_id, "CLOSED_NO_RESPONSE", note="Cierre manual")
    assert database.get_job_row(job_id)["application_stage"] == "CLOSED_NO_RESPONSE"


def _demo(database: JobDatabase):
    cases = [(1, "Data Analyst", "APPLIED", "linkedin", 60),
             (2, "BI Analyst", "HR_INTERVIEW", "greenhouse", 70),
             (3, "Business Analyst", "TECH_INTERVIEW", "lever", 80),
             (4, "Data Analyst", "REJECTED", "linkedin", 90),
             (5, "BI Analyst", "OFFER", "email", 86)]
    ids = []
    for number, title, stage, source, score in cases:
        job_id = stored(database, number, title=title, source=source, score=score); ids.append(job_id)
        database.mark_applied(job_id, channel="EMAIL" if source == "email" else "LINK",
                              at=f"2026-08-{20 + number:02d}T12:00:00+00:00")
        if stage != "APPLIED":
            database.set_application_stage(job_id, stage, at=f"2026-08-{21 + number:02d}T12:00:00+00:00")
    return ids


def test_analytics_rates_funnel_groups_and_time_series(tmp_path):
    database = JobDatabase(tmp_path / "demo.db"); ids = _demo(database)
    jobs = database.tracking_jobs(); histories = {job_id: database.application_history(job_id) for job_id in ids}
    data = analytics_snapshot(jobs, histories, datetime(2026, 8, 30, tzinfo=timezone.utc))
    assert data["rates"] == {"response_rate": 80.0, "interview_rate": 40.0, "offer_rate": 20.0, "hire_rate": 0.0}
    assert data["funnel"] == {"Postuladas": 5, "Respuestas": 4, "Entrevistas": 2,
                              "Finalistas": 1, "Ofertas": 1, "Contrataciones": 0}
    assert sum(row["applications"] for row in data["daily"]) == 5
    assert sum(row["applications"] for row in data["weekly"]) == 5
    assert {row["group"] for row in data["by_role"]} == {"Data Analyst", "BI Analyst", "Business Analyst"}
    assert {row["group"] for row in data["by_source"]} >= {"LinkedIn/manual", "Greenhouse", "Lever", "Email"}
    assert {row["group"] for row in data["by_channel"]} == {"LINK", "EMAIL"}
    assert {row["group"] for row in data["by_score"]} == {"55–64", "65–74", "75–84", "85–100"}
    timing = data["timings"]["time_to_first_response"]
    assert timing["count"] == 4 and timing["average"] == 1


def test_migration_is_idempotent_and_backfills_without_inventing_date(tmp_path):
    path = tmp_path / "legacy.db"; connection = sqlite3.connect(path)
    connection.execute("""CREATE TABLE jobs (id INTEGER PRIMARY KEY, title TEXT, company TEXT, location TEXT,
        work_mode TEXT, description TEXT, source TEXT, url TEXT UNIQUE, score REAL, decision TEXT,
        reasons TEXT, created_at TEXT, application_status TEXT, applied_at TEXT)""")
    connection.execute("""INSERT INTO jobs VALUES
        (1,'Data Analyst','Example','Argentina','remote','SQL','manual','https://x/1',80,'APPLY','{}','2026-01-01','APPLIED',NULL),
        (2,'BI Analyst','Example','Argentina','remote','BI','manual','https://x/2',80,'APPLY','{}','2026-01-01','NEW',NULL)""")
    connection.commit(); connection.close()
    first = JobDatabase(path); second = JobDatabase(path)
    assert first.get_job_row(1)["application_stage"] == "APPLIED" and first.get_job_row(1)["applied_at"] is None
    assert second.get_job_row(2)["application_stage"] == "NOT_APPLIED"
    with sqlite3.connect(path) as check:
        columns = [row[1] for row in check.execute("PRAGMA table_info(jobs)")]
        assert all(columns.count(name) == 1 for name in ("application_stage", "next_action_at", "offer_notes"))


def test_invalid_stage_and_duplicate_transition_are_rejected(tmp_path):
    database = JobDatabase(tmp_path / "jobs.db"); job_id = stored(database, 9)
    with pytest.raises(ValueError): database.set_application_stage(job_id, "UNKNOWN_STAGE")
    database.mark_applied(job_id)
    with pytest.raises(ValueError, match="already"): database.set_application_stage(job_id, "APPLIED")
    assert "CLOSED_NO_RESPONSE" in APPLICATION_STAGES


def test_tracking_cli_commands_do_not_fall_through(tmp_path, monkeypatch, capsys):
    path = tmp_path / "cli.db"; database = JobDatabase(path); job_id = stored(database, 10)
    monkeypatch.setattr(sys, "argv", ["job-hunter", "set-stage", str(job_id), "APPLIED", "--database", str(path)])
    main(); assert "APPLIED" in capsys.readouterr().out
    monkeypatch.setattr(sys, "argv", ["job-hunter", "application-history", str(job_id), "--database", str(path)])
    main(); assert "NOT_APPLIED -> APPLIED" in capsys.readouterr().out
    monkeypatch.setattr(sys, "argv", ["job-hunter", "tracking-summary", "--database", str(path)])
    main(); assert "active_processes=1" in capsys.readouterr().out
