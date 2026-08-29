from __future__ import annotations

from copy import deepcopy
from pathlib import Path

import pytest

from job_hunter.cv.adapter import adapt_cv
from job_hunter.cv.loader import load_master_cv
from job_hunter.cv.models import FactualBullet, FactualText, MetricFact
from job_hunter.cv.validator import CVValidationError, validate_cv
from job_hunter.models import Job

MASTER = Path("private/master_cv.yaml")


def target_job() -> Job:
    return Job(
        "Business / Data Analyst", "Fictional Company", "Buenos Aires", "hybrid",
        "SQL, Power BI, Excel, KPIs, análisis comercial, reporting, mejora de procesos y stakeholders.",
        "test", "https://example.com/business-data", id=999, score=72, decision="REVIEW",
    )


def test_real_loader_indexes_all_78_unique_ids():
    master = load_master_cv(MASTER)
    assert len(master.fact_index) == 78
    assert len(set(master.fact_index)) == 78


def test_summary_preserves_text_and_tags():
    fact = load_master_cv(MASTER).summary_facts[0]
    assert fact.id == "summary_01"
    assert fact.text == "Más de 20 años de experiencia en gestión comercial y operativa."
    assert fact.tags == ("business", "operations", "leadership")


def test_grouped_and_flat_skills_are_correct():
    master = load_master_cv(MASTER)
    assert set(master.skills_by_category) == {"business", "data", "technology"}
    assert "SQL" in master.all_skills and "Power BI" in master.all_skills
    assert "business" not in master.all_skills and "data" not in master.all_skills


@pytest.mark.parametrize("identifier", ["edu_01_fact_01", "course_03_fact_01", "lang_02_fact_01"])
def test_nested_facts_are_indexed(identifier):
    assert isinstance(load_master_cv(MASTER).fact_index[identifier], FactualText)


def test_project_metrics_are_indexed():
    assert isinstance(load_master_cv(MASTER).fact_index["project_01_metric_02"], MetricFact)


def test_course_fact_is_valid_source_and_unknown_source_is_invalid():
    master = load_master_cv(MASTER)
    cv = adapt_cv(target_job(), master)
    fact = master.fact_index["course_03_fact_01"]
    cv.project_sections[0].bullets.append(FactualBullet(fact.text, [fact.id]))
    validate_cv(cv, master)
    cv.project_sections[0].bullets[-1] = FactualBullet("Inventado", ["missing_fact"])
    with pytest.raises(CVValidationError, match="invalid facts"):
        validate_cv(cv, master)


def test_real_master_is_not_modified_and_generation_is_deterministic():
    before = MASTER.read_bytes()
    master = load_master_cv(MASTER)
    first = adapt_cv(target_job(), master)
    second = adapt_cv(deepcopy(target_job()), master)
    assert first == second
    assert MASTER.read_bytes() == before
