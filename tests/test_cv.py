from __future__ import annotations

from copy import deepcopy

import pytest

from job_hunter.cv.adapter import adapt_cv
from job_hunter.cv.loader import load_master_cv
from job_hunter.cv.models import FactualBullet
from job_hunter.cv.renderer import HTMLCVRenderer
from job_hunter.cv.validator import CVValidationError, validate_cv
from job_hunter.models import Job

MASTER_PATH = "config/master_cv.example.yaml"


def job(title: str, description: str = "", decision: str = "REVIEW") -> Job:
    return Job(
        title=title, company="Hiring Example", location="Argentina", work_mode="hybrid",
        description=description, source="test", url=f"https://example.com/{title}",
        id=123, score=70, decision=decision,
    )


def all_bullets(cv):
    return [bullet for section in [*cv.experience_sections, *cv.project_sections] for bullet in section.bullets]


def test_no_bullet_without_source_fact_ids():
    cv = adapt_cv(job("Data Analyst", "SQL Python Power BI"), load_master_cv(MASTER_PATH))
    assert all(bullet.source_fact_ids for bullet in all_bullets(cv))
    cv.experience_sections[0].bullets[0] = FactualBullet("Unsupported claim", [])
    with pytest.raises(CVValidationError, match="no source_fact_ids"):
        validate_cv(cv, load_master_cv(MASTER_PATH))


def test_no_nonexistent_technologies_or_companies():
    master = load_master_cv(MASTER_PATH)
    cv = adapt_cv(job("Data Analyst", "SQL Python Power BI Kubernetes"), master)
    technologies = {
        technology for section in [*cv.experience_sections, *cv.project_sections]
        for technology in section.technologies
    }
    companies = {section.company for section in cv.experience_sections}
    assert "Kubernetes" not in technologies
    assert companies <= {entry.company for entry in master.experience}


def test_data_analyst_prioritizes_data_skills():
    cv = adapt_cv(job("Data Analyst", "SQL Python Power BI data visualization"), load_master_cv(MASTER_PATH))
    assert set(cv.skills[:3]) == {"SQL", "Power BI", "Python"}


def test_pricing_analyst_prioritizes_commercial_experience():
    cv = adapt_cv(job("Pricing Analyst", "pricing Excel sales margin market"), load_master_cv(MASTER_PATH))
    assert "Pricing" in cv.skills
    assert "Python" not in cv.skills or cv.skills.index("Pricing") < cv.skills.index("Python")
    assert cv.experience_sections[0].company == "Example Retail Labs"
    assert any("ventas" in bullet.text.lower() or "márgenes" in bullet.text.lower() for bullet in cv.experience_sections[0].bullets)


def test_business_analyst_prioritizes_processes_and_kpis():
    cv = adapt_cv(job("Business Analyst", "process KPIs stakeholders business decisions"), load_master_cv(MASTER_PATH))
    assert "Business Analysis" in cv.skills
    assert "Python" not in cv.skills or cv.skills.index("Business Analysis") < cv.skills.index("Python")
    selected = " ".join(bullet.text for bullet in all_bullets(cv)).lower()
    assert "procesos" in selected
    assert "kpi" in selected


def test_reject_does_not_generate_without_explicit_override():
    rejected = job("Senior Data Analyst", "SQL", decision="REJECT")
    with pytest.raises(ValueError, match="disabled for REJECT"):
        adapt_cv(rejected, load_master_cv(MASTER_PATH))
    assert adapt_cv(rejected, load_master_cv(MASTER_PATH), allow_reject=True).validation_status == "VALID"


def test_html_output_is_valid_and_escaped():
    cv = adapt_cv(job("Data Analyst", "SQL & Python"), load_master_cv(MASTER_PATH))
    output = HTMLCVRenderer().render(cv)
    assert output.startswith("<!doctype html>")
    assert "<html" in output and "</html>" in output
    assert "source_fact_ids" not in output


def test_same_input_is_deterministic():
    master = load_master_cv(MASTER_PATH)
    target = job("Pricing Analyst", "pricing Excel margin")
    first = adapt_cv(deepcopy(target), master)
    second = adapt_cv(deepcopy(target), master)
    assert first == second
    assert HTMLCVRenderer().render(first) == HTMLCVRenderer().render(second)


def test_generation_does_not_modify_master_cv_file():
    before = open(MASTER_PATH, "rb").read()
    master = load_master_cv(MASTER_PATH)
    adapt_cv(job("Business Analyst", "process KPIs"), master)
    after = open(MASTER_PATH, "rb").read()
    assert before == after
