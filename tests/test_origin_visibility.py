from __future__ import annotations

from datetime import datetime, timezone

import pytest

from job_hunter.database import JobDatabase
from job_hunter.models import Job
from job_hunter.origin import (AUTOMATIC_DISCOVERY, MANUAL_FORM, MANUAL_TEXT, MANUAL_URL, UNKNOWN,
                               filter_jobs_by_origin, get_job_origin, jobs_created_by_run, origin_summary,
                               was_discovered_automatically)


def row(**values):
    return {"source": "", "url": "", "imported_manually": 0, "import_method": None,
            "first_seen_at": "2026-08-30T12:00:00+00:00", "imported_at": None, **values}


@pytest.mark.parametrize("source", ["remoteok", "greenhouse:acme", "lever:acme"])
def test_discovery_sources_are_automatic(source):
    assert get_job_origin(row(source=source, url="https://jobs.example/1")) == AUTOMATIC_DISCOVERY


@pytest.mark.parametrize(("values", "expected"), [
    ({"source": "manual:generic", "url": "https://example/1", "imported_manually": 1,
      "import_method": "PUBLIC_URL"}, MANUAL_URL),
    ({"source": "manual:text", "url": "manual://abc", "imported_manually": 1,
      "import_method": "PASTED_TEXT"}, MANUAL_TEXT),
    ({"source": "manual:user", "url": "https://example/2", "imported_manually": 1,
      "import_method": "MANUAL_FORM"}, MANUAL_FORM),
    ({"source": "legacy", "url": "manual://old"}, MANUAL_TEXT),
])
def test_manual_origins(values, expected):
    assert get_job_origin(row(**values)) == expected


def test_unknown_origin_is_not_invented():
    assert get_job_origin(row(source="legacy-csv", url="https://example/old")) == UNKNOWN


def test_origin_counts_and_filter_keep_manual_and_automatic_separate():
    rows = [row(id=1, source="remoteok"),
            row(id=2, source="manual:text", url="manual://2", imported_manually=1,
                import_method="PASTED_TEXT", imported_at="2026-08-30T13:00:00+00:00"),
            row(id=3, source="legacy")]
    summary = origin_summary(rows, datetime(2026, 8, 30, 15, tzinfo=timezone.utc))
    assert summary["automatic_today"] == 1 and summary["manual_today"] == 1
    assert [item["id"] for item in filter_jobs_by_origin(rows, "MANUAL")] == [2]
    assert [item["id"] for item in filter_jobs_by_origin(rows, AUTOMATIC_DISCOVERY)] == [1]


def test_latest_discovery_excludes_manual_imports_in_same_time_window():
    run = {"started_at": "2026-08-30T12:00:00+00:00", "finished_at": "2026-08-30T12:10:00+00:00"}
    rows = [row(id=1, source="greenhouse:acme", first_seen_at="2026-08-30T12:05:00+00:00"),
            row(id=2, source="manual:generic", url="https://x/2", imported_manually=1,
                import_method="PUBLIC_URL", first_seen_at="2026-08-30T12:06:00+00:00")]
    assert [item["id"] for item in jobs_created_by_run(rows, run)] == [1]


def test_manual_duplicate_later_discovered_automatically_keeps_id_and_initial_origin(tmp_path):
    database = JobDatabase(tmp_path / "jobs.db")
    manual = Job("Data Analyst", "Acme", "Argentina", "remote", "SQL", "manual:generic",
                 "https://jobs.example/1", imported_manually=True, imported_at="2026-08-30T12:00:00+00:00",
                 import_source_url="https://jobs.example/1", import_method="PUBLIC_URL", score=80,
                 decision="APPLY", reasons={})
    database.upsert(manual); original = database.list_jobs()[0]
    automatic = Job("Data Analyst", "Acme", "Argentina", "remote", "SQL", "greenhouse:acme",
                    "https://jobs.example/1", score=80, decision="APPLY", reasons={})
    assert database.upsert(automatic) is False
    rows = database.list_jobs(); assert len(rows) == 1 and rows[0]["id"] == original["id"]
    assert get_job_origin(rows[0]) == MANUAL_URL and was_discovered_automatically(rows[0])


def test_manual_import_does_not_change_discovery_run_metrics(tmp_path):
    database = JobDatabase(tmp_path / "jobs.db")
    run_id = database.create_discovery_run(["remoteok"], "2026-08-30T12:00:00+00:00")
    database.finish_discovery_run(run_id, status="COMPLETED", preliminary=3, new_jobs=1, updated_jobs=1,
                                  duplicates=1, apply_count=1, review_count=0, reject_count=0)
    before = database.latest_discovery_run()
    database.upsert(Job("BI Analyst", "Manual", "Argentina", "remote", "BI", "manual:text", "manual://x",
                        imported_manually=True, import_method="PASTED_TEXT", score=70, decision="REVIEW", reasons={}))
    after = database.latest_discovery_run()
    assert {key: before[key] for key in ("new_jobs", "updated_jobs", "duplicates")} == {
        key: after[key] for key in ("new_jobs", "updated_jobs", "duplicates")}
