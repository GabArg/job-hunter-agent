from __future__ import annotations

import json
from dataclasses import replace

import pytest

from job_hunter.config import load_profile
from job_hunter.discovery.factory import build_sources
from job_hunter.discovery.matching import geography_compatible, is_fresh, normalize_datetime
from job_hunter.discovery.models import RawJob
from job_hunter.discovery.probe import coverage_tags, detect_target, probe_target, write_probe_report
from job_hunter.discovery.sources.recruitee import RecruiteeSource
from job_hunter.discovery.sources.smartrecruiters import SmartRecruitersSource
from job_hunter.discovery.target_registry import TargetRegistry


@pytest.mark.parametrize(("url", "source_type", "token"), [
    ("https://job-boards.greenhouse.io/sezzle", "greenhouse", "sezzle"),
    ("https://jobs.lever.co/dlocal", "lever", "dlocal"),
    ("https://jobs.ashbyhq.com/ARQ", "ashby", "ARQ"),
    ("https://apply.workable.com/qodea", "workable", "qodea"),
])
def test_probe_detects_supported_ats(url, source_type, token):
    assert detect_target(url) == (source_type, token)


def test_probe_json_ld_and_unknown(monkeypatch):
    document = '<script type="application/ld+json">{"@type":"JobPosting","title":"Data Analyst","url":"https://x/job"}</script>'
    monkeypatch.setattr("job_hunter.discovery.probe.fetch_text", lambda _: document)
    result = probe_target("https://careers.example.com/jobs")
    assert result.status == "HEALTHY" and result.jobs_found == 1
    assert probe_target("not-a-url").status == "UNKNOWN"


def test_active_candidate_and_verification_metadata():
    registry = TargetRegistry.from_mapping({
        "active_targets": [{"company": "A", "source_type": "lever", "token": "a",
                            "verified_at": "2026-08-30", "verification_method": "public_ats_json",
                            "jobs_seen_at_verification": 3}],
        "candidate_targets": [{"company": "B", "url": "https://b.example/jobs"}],
    })
    assert [target.company for target in registry.active] == ["A"]
    assert [target.company for target in registry.candidates] == ["B"]
    assert registry.active[0].verified_at == "2026-08-30"
    assert registry.active[0].jobs_seen_at_verification == 3


def test_probe_report_is_separate_json(tmp_path):
    from job_hunter.discovery.probe import ProbeResult
    output = write_probe_report([ProbeResult("A", status="HEALTHY")], tmp_path)
    assert json.loads(output.read_text(encoding="utf-8"))[0]["company"] == "A"
    assert output.name.startswith("source_probe_")


def test_latam_eligibility_and_country_only_rejection():
    def job(location, description=""):
        return RawJob("1", "Data Analyst", "A", location, "remote", description, "x", "https://x/1")
    assert geography_compatible(job("Remote LATAM"), ["Argentina"])[0]
    assert geography_compatible(job("LATAM", "Argentina and Brazil only"), ["Argentina"])[0]
    assert not geography_compatible(job("Remote", "Brazil only"), ["Argentina"])[0]
    assert not geography_compatible(job("Remote", "Mexico only"), ["Argentina"])[0]


def test_recruitee_utc_timestamp_is_normalized_and_filtered():
    assert normalize_datetime("2026-08-30 03:20:00 UTC") == "2026-08-30T03:20:00+00:00"
    assert not is_fresh("2026-07-08 15:10:18 UTC", 14)


def test_coverage_tags():
    tags = coverage_tags(["Data Analyst", "Business Operations Analyst", "Revenue Performance Analyst"])
    assert {"data", "business", "operations", "revenue", "performance"} <= set(tags)


def test_recruitee_adapter_mapping():
    payload = {"offers": [{"id": 1, "slug": "data", "title": "Analista de Datos",
        "description": "SQL", "requirements": "Power BI", "locations": [{"city": "Buenos Aires", "country": "Argentina"}],
        "careers_url": "https://acme.recruitee.com/o/data", "published_at": "2026-08-30"}]}
    source = RecruiteeSource("Acme", "acme", fetcher=lambda _: payload)
    result = source.discover("Analista de Datos")
    assert result[0].company == "Acme" and "Argentina" in result[0].location


def test_smartrecruiters_adapter_mapping():
    payload = {"content": [{"id": "1", "name": "Business Analyst", "location": {"city": "Buenos Aires", "country": "ar"},
        "ref": "https://jobs.smartrecruiters.com/acme/1", "releasedDate": "2026-08-30"}]}
    result = SmartRecruitersSource("Acme", "acme", fetcher=lambda _: payload).discover("Business Analyst")
    assert result[0].title == "Business Analyst" and "Buenos Aires" in result[0].location


def test_factory_supports_new_adapters_and_legacy_config():
    profile = load_profile("config/profile.example.yaml")
    profile = replace(profile, discovery_targets={}, active_targets=[
        {"company": "R", "source_type": "recruitee", "token": "r"},
        {"company": "S", "source_type": "smartrecruiters", "token": "s"}],
        candidate_targets=[], career_targets=[])
    assert {source.name for source in build_sources(profile, ["recruitee", "smartrecruiters"])} == {"recruitee:R", "smartrecruiters:S"}


def test_public_profile_has_verified_active_targets():
    profile = load_profile("config/profile.example.yaml")
    registry = TargetRegistry.from_mapping({"discovery_targets": profile.discovery_targets,
        "active_targets": profile.active_targets, "candidate_targets": profile.candidate_targets})
    assert len(registry.active) >= 20
    assert all(target.verified_at and target.verification_method for target in registry.active)
