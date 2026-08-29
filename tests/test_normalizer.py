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
