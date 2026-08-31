from __future__ import annotations

from pathlib import Path

import pytest

from job_hunter.config import load_profile
from job_hunter.database import JobDatabase
from job_hunter.models import Job
from job_hunter.normalizer import _extract_english, normalize_job
from job_hunter.pipeline import _load_master_capabilities
from job_hunter.scorer import score_job


PROFILE = load_profile("config/profile.example.yaml")


@pytest.mark.parametrize(("text", "expected"), [
    ("excellent level of English required", "advanced"),
    ("fluent English required", "fluent"),
    ("advanced English mandatory", "advanced"),
    ("English C1 required", "advanced"),
    ("English B2 required", "upper-intermediate"),
    ("inglés avanzado excluyente", "advanced"),
    ("excelente nivel de inglés obligatorio", "advanced"),
])
def test_mandatory_english_levels_are_canonical(text, expected):
    assert _extract_english(text) == expected


def test_desirable_excellent_english_is_not_a_hard_requirement():
    assert _extract_english("Excellent English is a plus") is None
    assert _extract_english("Excellent English preferred") is None


@pytest.mark.parametrize("text", [
    "English documentation",
    "Ability to read technical documentation in English",
    "Lectura de documentación técnica en inglés",
])
def test_technical_reading_does_not_become_advanced(text):
    assert _extract_english(text) is None


def _evaluate(english: str):
    job = Job("Pricing Analyst Junior", "Example", "Buenos Aires", "hybrid",
              f"Excel SQL pricing. {english}", "test", "https://example.test/english")
    normalized = normalize_job(job, PROFILE.skills)
    return normalized, score_job(normalized, PROFILE)


def test_intermediate_candidate_is_rejected_for_advanced_without_changing_technical_score():
    compatible_job, compatible = _evaluate("Intermediate English required")
    advanced_job, advanced = _evaluate("Excellent level of English required")
    assert compatible_job.required_english == "intermediate" and advanced_job.required_english == "advanced"
    assert compatible.score == advanced.score
    assert compatible.decision != "REJECT" and not compatible.hard_reject_reasons
    assert advanced.decision == "REJECT"
    assert advanced.hard_reject_reasons == [
        "Nivel de inglés requerido (advanced) supera el nivel del candidato (intermediate)"
    ]


def test_infotree_years_hard_reject_is_unchanged():
    job = Job("Data Analyst", "InfoTree Example", "Buenos Aires", "remote",
              "SQL. 5 años de experiencia.", "test", "https://example.test/infotree")
    result = score_job(normalize_job(job, PROFILE.skills), PROFILE)
    assert any("5" in reason and "Experiencia" in reason for reason in result.hard_reject_reasons)


def test_local_caramel_and_redbee_regressions_when_available():
    path = Path("data/jobs.db")
    if not path.is_file(): pytest.skip("Local production-like DB is not available")
    database = JobDatabase(path); profile = load_profile("config/profile.yaml")
    capabilities = _load_master_capabilities()
    caramel = database.get_job(job_id=33)
    if caramel is None: pytest.skip("Local Caramel job #33 is not available")
    caramel_result = score_job(normalize_job(caramel, profile.skills), profile, capabilities)
    assert caramel.required_english == "advanced"
    assert (caramel_result.score, caramel_result.decision) == (85.0, "REJECT")
    assert caramel_result.hard_reject_reasons == [
        "Nivel de inglés requerido (advanced) supera el nivel del candidato (intermediate)"
    ]
    redbee_row = next((row for row in database.list_jobs() if "redbee" in row["company"].casefold()), None)
    if redbee_row:
        redbee = database.get_job(job_id=redbee_row["id"])
        result = score_job(normalize_job(redbee, profile.skills), profile, capabilities)
        assert (result.score, result.decision, result.hard_reject_reasons) == (70.38, "REVIEW", [])
