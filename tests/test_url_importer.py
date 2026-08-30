from __future__ import annotations

from urllib.error import HTTPError
from urllib.request import Request
import json

import pytest

from job_hunter.config import load_profile
from job_hunter.database import JobDatabase
from job_hunter.importer import ImportStatus, detect_source_type, import_job_from_url, import_manual_job, validate_public_url
from job_hunter.importer.extractors import extract_job
from job_hunter.importer.url_importer import _SafeRedirect


PROFILE = load_profile("config/profile.example.yaml")


@pytest.mark.parametrize(("url", "expected"), [
    ("https://www.linkedin.com/jobs/view/123", "linkedin"),
    ("https://job-boards.greenhouse.io/acme/jobs/1", "greenhouse"),
    ("https://jobs.lever.co/acme/1", "lever"),
    ("https://jobs.ashbyhq.com/acme/1", "ashby"),
    ("https://apply.workable.com/acme/j/1", "workable"),
    ("https://jobs.smartrecruiters.com/acme/1", "smartrecruiters"),
    ("https://acme.recruitee.com/o/job", "recruitee"),
    ("https://careers.example.com/job", "generic"),
])
def test_source_detection(url, expected):
    assert detect_source_type(url) == expected


def test_unknown_source_detection():
    assert detect_source_type("https://example.com/about") == "unknown"


def json_ld(description="SQL Power BI reporting", url="https://careers.example.com/job"):
    payload = {"@type":"JobPosting", "title":"Data Analyst", "hiringOrganization":{"name":"Acme"},
        "jobLocation":{"address":{"addressLocality":"Buenos Aires","addressCountry":"Argentina"}},
        "description":f"<p>{description}</p>", "datePosted":"2026-08-30", "url":url}
    return '<script type="application/ld+json">' + json.dumps(payload) + '</script>'


def test_generic_jsonld_import_uses_pipeline_and_channel(tmp_path):
    db = JobDatabase(tmp_path / "jobs.db")
    result = import_job_from_url("https://careers.example.com/job", PROFILE, db,
        fetcher=lambda url: (url, json_ld("SQL Power BI. Enviar CV a rrhh@acme.com")))
    assert result.status == ImportStatus.IMPORTED and result.score is not None and result.decision
    assert result.application_method in {"EMAIL", "LINK_EMAIL"}
    assert db.get_job_row(result.job_id)["source"] == "manual:generic"


def test_linkedin_public_valid_and_insufficient_fallback(tmp_path):
    db = JobDatabase(tmp_path / "jobs.db"); url = "https://www.linkedin.com/jobs/view/123"
    valid = import_job_from_url(url, PROFILE, db, fetcher=lambda _: (url, json_ld(url=url)))
    assert valid.status == ImportStatus.IMPORTED and valid.source_type == "linkedin"
    insufficient = import_job_from_url("https://www.linkedin.com/jobs/view/456", PROFILE, db,
        fetcher=lambda u: (u, "<html><title>LinkedIn</title></html>"))
    assert insufficient.status == ImportStatus.NEEDS_MANUAL_INPUT


def test_greenhouse_url_uses_structured_public_content(tmp_path):
    db = JobDatabase(tmp_path / "jobs.db"); url = "https://job-boards.greenhouse.io/acme/jobs/1"
    result = import_job_from_url(url, PROFILE, db, fetcher=lambda _: (url, json_ld(url=url)))
    assert result.status == ImportStatus.IMPORTED and result.source_type == "greenhouse"
    assert db.get_job_row(result.job_id)["source"] == "manual:greenhouse"


def test_missing_description_needs_manual_and_does_not_insert(tmp_path):
    db = JobDatabase(tmp_path / "jobs.db")
    html = '<meta property="og:title" content="Data Analyst"><meta property="og:site_name" content="Acme">'
    result = import_job_from_url("https://careers.example.com/x", PROFILE, db, fetcher=lambda u: (u, html))
    assert result.status == ImportStatus.NEEDS_MANUAL_INPUT and db.list_jobs() == []


def test_invalid_url_localhost_and_private_ip_are_blocked(tmp_path):
    db = JobDatabase(tmp_path / "jobs.db")
    assert import_job_from_url("file:///etc/passwd", PROFILE, db).status == ImportStatus.UNSUPPORTED
    assert import_job_from_url("http://localhost/job", PROFILE, db).status == ImportStatus.UNSUPPORTED
    assert import_job_from_url("http://127.0.0.1/job", PROFILE, db).status == ImportStatus.UNSUPPORTED
    with pytest.raises(ValueError): validate_public_url("http://10.1.2.3/job")


def test_dns_private_ip_is_blocked():
    resolver = lambda *args, **kwargs: [(2, 1, 6, "", ("192.168.1.2", 443))]
    with pytest.raises(ValueError): validate_public_url("https://internal.example/job", resolver)


def test_redirect_limit():
    handler = _SafeRedirect(5, lambda *a, **k: [(2, 1, 6, "", ("93.184.216.34", 443))])
    request = Request("https://example.com/a", headers={"X-JobHunter-Redirects": "5"})
    with pytest.raises(HTTPError): handler.redirect_request(request, None, 302, "Found", {}, "https://example.com/b")


def test_duplicate_by_url_and_fingerprint(tmp_path):
    db = JobDatabase(tmp_path / "jobs.db")
    first = import_manual_job({"url":"https://example.com/1","title":"Data Analyst","company":"Acme",
        "location":"Argentina","description":"SQL reporting"}, PROFILE, db)
    same_url = import_manual_job({"url":"https://example.com/1?utm_source=x","title":"Other","company":"Other",
        "description":"Other description"}, PROFILE, db)
    fingerprint = import_manual_job({"url":"https://example.com/2","title":"Data Analyst","company":"Acme",
        "location":"Argentina","description":"SQL reporting"}, PROFILE, db)
    assert first.status == ImportStatus.IMPORTED
    assert same_url.status == fingerprint.status == ImportStatus.DUPLICATE
    assert same_url.duplicate_job_id == fingerprint.duplicate_job_id == first.job_id
    assert len(db.list_jobs()) == 1


def test_valid_manual_form_and_pasted_text_inference(tmp_path):
    db = JobDatabase(tmp_path / "jobs.db")
    manual = import_manual_job({"url":"https://example.com/manual","title":"Business Analyst","company":"Acme",
        "location":"Argentina","work_mode":"hybrid","description":"Requirements and stakeholder reporting"}, PROFILE, db)
    pasted = import_manual_job({"description":"Pricing Analyst\nEmpresa: RetailCo\nUbicación: Buenos Aires\nExcel pricing rentabilidad"},
                               PROFILE, db, method="PASTED_TEXT")
    assert manual.status == pasted.status == ImportStatus.IMPORTED
    assert pasted.title.casefold() == "pricing analyst" and pasted.company == "RetailCo"
    assert db.get_job_row(pasted.job_id)["import_method"] == "PASTED_TEXT"


def test_html_is_sanitized():
    job, method = extract_job(json_ld("SQL <style>evil</style><b>reporting</b>"), "https://x/job")
    assert method == "JSON_LD" and "evil" not in job.description and "<b>" not in job.description


def test_network_error_is_safe_and_no_insert(tmp_path):
    db = JobDatabase(tmp_path / "jobs.db")
    def broken(_): raise TimeoutError("timed out")
    result = import_job_from_url("https://careers.example.com/job", PROFILE, db, fetcher=broken)
    assert result.status == ImportStatus.FAILED and result.warnings and db.list_jobs() == []
    assert db.list_import_history()[0]["result"] == "FAILED"


def test_legacy_discovery_database_still_initializes(tmp_path):
    db = JobDatabase(tmp_path / "legacy-compatible.db")
    assert db.list_jobs() == [] and db.list_import_history() == []
