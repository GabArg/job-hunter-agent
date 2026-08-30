from __future__ import annotations

import json

import pytest

from job_hunter.config import load_profile
from job_hunter.database import JobDatabase
from job_hunter.discovery.target_registry import detect_sector
from job_hunter.importer import ImportStatus, import_job_from_url, import_manual_job
from job_hunter.models import Job
from job_hunter.normalizer import normalize_job
from job_hunter.scorer import score_job


PROFILE = load_profile("config/profile.example.yaml")


@pytest.mark.parametrize(("company", "description", "expected"), [
    ("Accenture Argentina", "strategy consulting", "Consulting"),
    ("KPMG", "servicios profesionales", "Consulting"),
    ("dLocal", "payments infrastructure", "Fintech"),
    ("PedidosYa", "delivery marketplace", "E-commerce"),
    ("Globant", "digital products", "Technology"),
])
def test_known_company_sector(company, description, expected):
    sector, confidence = detect_sector(company, description)
    assert sector == expected and confidence >= 0.9


def test_sector_keyword_fallback_and_ambiguous():
    assert detect_sector("Example", "professional services and advisory")[0] == "Consulting"
    assert detect_sector("Example", "general administrative position") == ("Other", 0.2)
    assert detect_sector("Honeywell", "general administrative position") == ("Other", 0.2)


def test_manual_import_assigns_sector(tmp_path):
    database = JobDatabase(tmp_path / "jobs.db")
    result = import_manual_job({"title": "Strategy & Consulting", "company": "Accenture Argentina",
        "description": "Data and Applied Intelligence consulting", "location": "Buenos Aires"}, PROFILE, database)
    assert result.status == ImportStatus.IMPORTED
    row = database.get_job_row(result.job_id)
    assert row["sector"] == "Consulting" and row["sector_confidence"] >= 0.9


def test_url_import_assigns_sector(tmp_path):
    database = JobDatabase(tmp_path / "jobs.db")
    url = "https://careers.example.com/jobs/1"
    payload = {"@type": "JobPosting", "title": "Payments Analyst",
        "hiringOrganization": {"name": "dLocal"}, "description": "payments analytics", "url": url}
    html = '<script type="application/ld+json">' + json.dumps(payload) + "</script>"
    result = import_job_from_url(url, PROFILE, database, fetcher=lambda value: (value, html))
    row = database.get_job_row(result.job_id)
    assert result.status == ImportStatus.IMPORTED and row["sector"] == "Fintech"


def _legacy_accenture(database: JobDatabase) -> int:
    job = Job("Strategy & Consulting", "Accenture Argentina", "Buenos Aires", "hybrid",
              "Data and Applied Intelligence", "manual:user", "https://example.com/accenture",
              score=52.5, decision="REJECT", imported_manually=True, sector="Other", sector_confidence=0.2)
    database.upsert(job)
    return int(database.get_job(url=job.url).id)


def test_enrich_dry_run_does_not_modify_database(tmp_path):
    database = JobDatabase(tmp_path / "jobs.db"); job_id = _legacy_accenture(database)
    result = database.enrich_job_sectors(manual_only=True, apply=False)
    assert result["changes"][0]["sector_after"] == "Consulting" and result["updated"] == 0
    assert database.get_job_row(job_id)["sector"] == "Other"


def test_enrich_apply_only_changes_sector_and_creates_backup(tmp_path):
    database = JobDatabase(tmp_path / "jobs.db"); job_id = _legacy_accenture(database)
    before = database.get_job_row(job_id)
    result = database.enrich_job_sectors(manual_only=True, apply=True)
    after = database.get_job_row(job_id)
    assert result["updated"] == 1 and result["backup"]
    assert after["sector"] == "Consulting" and after["sector_confidence"] == pytest.approx(0.95)
    for field in ("score", "decision", "application_status"):
        assert after[field] == before[field]


def test_location_and_work_mode_do_not_create_apply_alone():
    job = Job("Office Assistant", "Unknown", "Argentina", "remote",
              "General administrative support", "manual:user", "https://example.com/mismatch")
    normalize_job(job, PROFILE.skills)
    result = score_job(job, PROFILE)
    assert result.decision != "APPLY" and result.score < 75


def test_detect_sector_backward_compatible_two_arguments():
    sector, confidence = detect_sector("Example", "logistics and shipping")
    assert sector == "Logistics" and confidence > 0
