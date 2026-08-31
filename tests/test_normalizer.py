from job_hunter.models import Job
from job_hunter.normalizer import normalize_job


def make_job(**overrides):
    values = {
        "title": "Senior Data Analyst",
        "company": "Company",
        "location": "Buenos Aires",
        "work_mode": "Remoto",
        "description": "Inglés fluido obligatorio. SQL. 5 años de experiencia.",
        "source": "Test",
        "url": "https://example.com/1",
    }
    values.update(overrides)
    return Job(**values)


def test_normalizes_and_extracts_job_signals():
    job = normalize_job(make_job(), ["sql", "power bi"])
    assert job.title == "senior data analyst"
    assert job.work_mode == "remote"
    assert job.seniority == "senior"
    assert job.required_english == "fluent"
    assert job.required_years == 5
    assert job.detected_skills == ["sql"]


def test_extracts_semi_senior_before_senior():
    job = normalize_job(make_job(title="Business Analyst Semi-Senior", description="Excel"), ["excel"])
    assert job.seniority == "semi-senior"


def test_company_age_is_not_candidate_experience_requirement():
    job = normalize_job(make_job(
        title="Business Analyst Ssr",
        description="Empresa argentina con más de 14 años de experiencia redefiniendo productos.",
    ))
    assert job.required_years is None


def test_advanced_excel_is_not_advanced_english():
    job = normalize_job(make_job(
        title="Analista Junior Pricing",
        description="Se requiere manejo avanzado de Excel y capacidad analítica.",
    ))
    assert job.required_english is None


def test_seniority_uses_role_context_and_prioritizes_title():
    cases = [
        ("Junior Data Analyst", "Tu responsabilidad principal será construir dashboards.", "junior"),
        ("Junior Data Analyst", "El objetivo principal es mejorar el reporting.", "junior"),
        ("Principal Data Analyst", "Construir dashboards.", "principal"),
        ("Data Analyst - Principal", "Construir dashboards.", "principal"),
        ("Junior Data Analyst", "Support lead generation campaigns.", "junior"),
        ("Lead Data Analyst", "Construir dashboards.", "lead"),
        ("Junior Data Analyst", "Work with senior stakeholders.", "junior"),
        ("Senior Data Analyst", "Construir dashboards.", "senior"),
        ("Analista de Datos Junior", "La función principal será crear tableros.", "junior"),
    ]
    for title, description, expected in cases:
        assert normalize_job(make_job(title=title, description=description)).seniority == expected


def test_seniority_conflict_is_preserved_as_evidence_without_overriding_title():
    job = normalize_job(make_job(
        title="Junior Data Analyst",
        description="The description explicitly says Senior Data Analyst required.",
        raw_data={},
    ))
    assert job.seniority == "junior"
    assert job.seniority_evidence == {
        "title": "junior",
        "description": "senior",
        "conflict": True,
    }
