from __future__ import annotations

from copy import deepcopy
from pathlib import Path

from job_hunter.cv.adapter import adapt_cv
from job_hunter.cv.loader import load_master_cv
from job_hunter.cv.selector import semantic_duplicate
from job_hunter.models import Job

MASTER_PATH = Path("private/master_cv.yaml")


def target(description: str | None = None) -> Job:
    return Job(
        "Business / Data Analyst", "Fictional Company", "Buenos Aires", "hybrid",
        description or "SQL, Power BI, Excel, KPIs, procesos, análisis comercial, reporting y stakeholders.",
        "test", "https://example.com/editorial", id=707, score=72, decision="REVIEW",
    )


def test_summary_is_narrative_not_literal_concatenation_and_keeps_sources():
    master = load_master_cv(MASTER_PATH)
    cv = adapt_cv(target(), master)
    literal = " ".join(master.fact_index[identifier].text for identifier in cv.professional_summary_source_fact_ids)
    assert cv.professional_summary != literal
    assert 3 <= len([part for part in cv.professional_summary.split(".") if part.strip()]) <= 4
    assert cv.professional_summary_source_fact_ids


def test_concise_has_at_most_twelve_skills():
    cv = adapt_cv(target(), load_master_cv(MASTER_PATH))
    assert len(cv.skills) <= 12
    assert {"SQL", "Power BI", "Excel"} <= set(cv.skills)


def test_business_data_impact_ranks_alixpartners_first():
    cv = adapt_cv(
        target("SQL Power BI negocio optimización costos impacto decisiones supply logistics"),
        load_master_cv(MASTER_PATH),
    )
    assert cv.project_sections[0].name == "AlixPartners Data Challenge 2026 — Bonsai Corp"


def test_nodoquant_is_deprioritized_without_quant_fintech_or_risk():
    cv = adapt_cv(target(), load_master_cv(MASTER_PATH))
    names = [section.name for section in cv.project_sections]
    assert "NodoQuant" not in names or names.index("NodoQuant") == len(names) - 1


def test_selected_bullets_have_no_semantic_duplicates():
    master = load_master_cv(MASTER_PATH)
    cv = adapt_cv(target(), master)
    for section in cv.experience_sections:
        facts = [master.fact_index[bullet.source_fact_ids[0]] for bullet in section.bullets]
        assert not any(semantic_duplicate(first, second) for index, first in enumerate(facts) for second in facts[index + 1:])


def test_recent_experience_has_more_space_than_old_experience():
    cv = adapt_cv(target(), load_master_cv(MASTER_PATH))
    counts = {section.company: len(section.bullets) for section in cv.experience_sections}
    assert counts["Esquinas Adrogué S.R.L."] > counts["Experiencia Comercial y Operativa"]


def test_rewrites_keep_factual_evidence():
    master = load_master_cv(MASTER_PATH)
    cv = adapt_cv(target(), master)
    rewritten = [
        bullet for section in cv.experience_sections for bullet in section.bullets
        if bullet.text != master.fact_index[bullet.source_fact_ids[0]].text
    ]
    assert rewritten
    assert all(bullet.source_fact_ids and bullet.source_fact_ids[0] in master.factual_ids for bullet in rewritten)
    assert cv.validation_status == "VALID"


def test_editorial_generation_is_deterministic_and_master_unchanged():
    before = MASTER_PATH.read_bytes()
    master = load_master_cv(MASTER_PATH)
    assert adapt_cv(target(), master) == adapt_cv(deepcopy(target()), master)
    assert MASTER_PATH.read_bytes() == before
