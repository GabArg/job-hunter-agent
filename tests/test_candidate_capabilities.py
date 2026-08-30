from __future__ import annotations

from dataclasses import replace

from job_hunter.config import load_profile
from job_hunter.cv.loader import load_master_cv
from job_hunter.models import Job
from job_hunter.normalizer import normalize_job
from job_hunter.scorer import score_job
from job_hunter.semantics import build_candidate_capabilities


PROFILE = load_profile("config/profile.example.yaml")
MASTER = load_master_cv("private/master_cv.yaml")
CAPABILITIES = build_candidate_capabilities(MASTER)
INFOTREE_DESCRIPTION = """
Buscamos Data Analyst con 3 años de experiencia en Data Analysis, Business Intelligence,
reporting, dashboards y relevamiento de requirements. Requisitos: Excel, Power BI, SQL,
Python, Generative AI y automation.
"""


def evaluate(title: str, description: str):
    job = normalize_job(Job(title, "Example", "Argentina", "hybrid", description, "test", "https://example.test/job"), PROFILE.skills)
    return job, score_job(job, PROFILE, CAPABILITIES)


def test_master_factual_capabilities_cover_observed_false_gaps():
    expected = {"python", "reporting", "dashboard", "automation", "generative-ai", "data-analysis"}
    assert expected <= set(CAPABILITIES)
    assert all(CAPABILITIES[concept] for concept in expected)


def test_project_and_course_facts_are_auditable_capability_evidence():
    assert "project_01_fact_02" in CAPABILITIES["data-analysis"]
    assert "course_03_fact_01" in CAPABILITIES["python"]
    assert "project_04_fact_01" in CAPABILITIES["dashboard"]


def test_unknown_requirement_remains_a_gap():
    _, result = evaluate("Data Analyst", "Python, Tableau y Snowflake")
    assert "python" in result.matched_requirements
    assert {"tableau", "snowflake"}.isdisjoint(CAPABILITIES)
    assert {"tableau", "snowflake"} <= set(result.missing_skills)


def test_target_role_alone_never_creates_candidate_capability():
    profile = replace(PROFILE, target_roles=["Data Analyst"], skills=[])
    job = normalize_job(Job("Data Analyst", "X", "Argentina", "hybrid", "Data analysis", "test", "https://example.test/target"), [])
    result = score_job(job, profile, {})
    assert result.missing_skills == ["data-analysis"]


def test_infotree_false_gaps_are_corrected_but_years_reject_remains():
    job, result = evaluate("Data Analyst", INFOTREE_DESCRIPTION)
    expected = {"data-analysis", "business-intelligence", "reporting", "dashboard", "requirements",
                "excel", "power-bi", "sql", "python", "generative-ai", "automation"}
    assert expected <= set(job.job_requirements)
    assert expected <= set(result.matched_requirements)
    assert not expected & set(result.missing_skills)
    assert result.decision == "REJECT"
    assert any("3 años" in reason and "máximo (2" in reason for reason in result.hard_reject_reasons)
    assert result.matched_requirement_evidence["python"]


def test_capability_index_and_matches_have_no_duplicates():
    assert len(CAPABILITIES) == len(set(CAPABILITIES))
    assert all(len(sources) == len(set(sources)) for sources in CAPABILITIES.values())
    _, result = evaluate("BI Analyst", "Reporting dashboards Power BI SQL Python")
    assert len(result.matched_requirements) == len(set(result.matched_requirements))
    assert result.as_dict()["matched_requirement_evidence"]
