from __future__ import annotations

from dataclasses import replace
from datetime import timezone

import pytest

from job_hunter.config import load_profile
from job_hunter.database import JobDatabase
from job_hunter.discovery.matching import normalize_datetime, parse_datetime, title_matches
from job_hunter.discovery.sources.lever import LeverSource
from job_hunter.models import Job
from job_hunter.normalizer import normalize_job
from job_hunter.scorer import normalize_reason_list, score_job
from job_hunter.semantics import detect_concepts, detect_roles, expand_target_roles, roles_match

PROFILE = load_profile("config/profile.example.yaml")
REDBEE_DESCRIPTION = """
Analizar y documentar las diferentes características de un producto, considerando aspectos de negocio y técnicos.
Aplicar buenas prácticas para definir un backlog y documentar historias de usuario.
Participar en reuniones de entendimiento de requerimientos. Trabajar el alcance dentro de un marco agil.
Actualizar las prioridades del product backlog según el roadmap, negociando con el Product Owner.
Experiencia realizando historias de usuario y diagramas UML. Conocimientos de servicios y capacidad de testearlos.
Entendimiento de la arquitectura de un sistema como ventaja. Experiencia haciendo slicing de una funcionalidad.
Capacidad analítica y skills de negociacion. Experiencia en story mapping e impact mapping.
"""


@pytest.mark.parametrize(("english", "spanish", "canonical"), [
    ("Data Analyst", "Analista de Datos", "data-analyst"),
    ("Business Analyst", "Analista de Negocios", "business-analyst"),
])
def test_bilingual_roles_share_canonical_concept(english, spanish, canonical):
    assert canonical in detect_roles(english) and canonical in detect_roles(spanish)
    assert roles_match(english, spanish)


@pytest.mark.parametrize(("english", "spanish", "canonical"), [
    ("reporting", "reportes", "reporting"), ("dashboard", "tableros", "dashboard"),
    ("pricing", "análisis de precios", "pricing"), ("profitability", "rentabilidad y márgenes", "profitability"),
    ("requirements", "requerimientos", "requirements"), ("user stories", "historias de usuario", "user-stories"),
    ("agile", "metodologias agiles", "agile"),
])
def test_english_and_spanish_aliases_produce_same_concept(english, spanish, canonical):
    assert canonical in detect_concepts(english)
    assert canonical in detect_concepts(spanish)


def redbee_result():
    job = Job("Ssr Business Analyst", "redbee", "Buenos Aires", "Hybrid", REDBEE_DESCRIPTION,
              "lever:redbee", "https://jobs.lever.co/redbee/6e049529-1f53-44a7-b952-553c907149ef")
    normalized = normalize_job(job, PROFILE.skills)
    return normalized, score_job(normalized, PROFILE)


def test_redbee_requirements_and_real_gaps():
    job, result = redbee_result()
    expected = {"uml", "user-stories", "backlog", "requirements", "agile", "product-owner", "slicing",
                "service-testing", "story-mapping", "impact-mapping", "negotiation"}
    assert expected <= set(job.job_requirements)
    assert not {"excel", "sql", "power-bi", "pricing"} & set(result.missing_skills)
    assert "requirements" in result.matched_requirements
    assert result.decision == "REVIEW"


def test_target_profile_terms_do_not_contaminate_missing_skills():
    profile = replace(PROFILE, skills=["excel", "sql", "power bi", "pricing"])
    job = normalize_job(Job("Business Analyst", "X", "Argentina", "Hybrid", "UML y backlog", "x", "https://x"), profile.skills)
    result = score_job(job, profile)
    assert set(result.missing_skills) == {"uml", "backlog"}
    assert not set(profile.skills) & set(result.missing_skills)


def test_hard_reject_placeholders_are_removed():
    assert normalize_reason_list(["-", "—", "none", "N/A", "null", "no", ""]) == []


def test_seconds_and_milliseconds_timestamps_are_timezone_aware():
    seconds, milliseconds = 1787230016, 1787230016000
    parsed_seconds, parsed_milliseconds = parse_datetime(seconds), parse_datetime(milliseconds)
    assert parsed_seconds == parsed_milliseconds
    assert parsed_seconds.tzinfo == timezone.utc
    assert normalize_datetime(milliseconds) == "2026-08-20T12:46:56+00:00"


def test_lever_keeps_lists_and_normalizes_millisecond_timestamp():
    source = LeverSource("redbee", "redbee", fetcher=lambda _: [{
        "id": "r1", "text": "Ssr Business Analyst", "categories": {"location": "Buenos Aires"},
        "descriptionPlain": "Introducción", "lists": [{"text": "Requisitos", "content": "Historias de usuario, UML y backlog"}],
        "hostedUrl": "https://jobs.lever.co/redbee/r1", "workplaceType": "hybrid", "createdAt": 1787230016368,
    }])
    raw = source.discover("Business Analyst")[0]
    assert "Historias de usuario" in raw.description and "UML" in raw.description
    assert raw.published_at == "2026-08-20T12:46:56+00:00"


def test_discovery_expands_target_roles_bilingually():
    expanded = expand_target_roles(["Data Analyst", "Business Analyst", "Pricing Analyst", "Operations Analyst"])
    assert {"analista de datos", "analista funcional", "analista de precios", "analista de operaciones"} <= set(expanded)


def test_commercial_analyst_needs_pricing_signals_for_pricing_role():
    assert "pricing-analyst" not in detect_roles("Analista Comercial", "Gestión general de clientes")
    assert "pricing-analyst" in detect_roles("Analista Comercial", "Análisis de precios, márgenes y rentabilidad")


def test_semantic_reasons_survive_rediscovery_without_status_reset(tmp_path):
    database = JobDatabase(tmp_path / "jobs.db")
    job, result = redbee_result(); job.score, job.decision, job.reasons = result.score, result.decision, result.as_dict()
    database.upsert(job); row = database.list_jobs()[0]; database.set_application_status(row["id"], "SHORTLISTED")
    database.upsert(job); refreshed = database.get_job_row(row["id"])
    assert refreshed["application_status"] == "SHORTLISTED"
    assert "uml" in refreshed["reasons"]


def test_functional_analyst_is_business_affinity_not_data_by_default():
    roles = detect_roles("Analista Funcional", "Historias de usuario, backlog y UML")
    assert "business-analyst-functional" in roles
    assert "business-analyst-data" not in roles
    assert title_matches("Analista Funcional", ["Business Analyst"], "Historias de usuario")
