from job_hunter.config import load_profile
from job_hunter.models import Job
from job_hunter.normalizer import normalize_job
from job_hunter.scorer import score_job


PROFILE = load_profile("config/profile.example.yaml")


def evaluate(title: str, description: str, location="Buenos Aires", mode="Hybrid"):
    job = Job(title, "Test", location, mode, description, "test", "https://example.com/job")
    return score_job(normalize_job(job, PROFILE.skills), PROFILE)


def test_pricing_junior_is_apply_and_explainable():
    result = evaluate(
        "Pricing Analyst Junior",
        "Excel, SQL y pricing. Inglés intermedio. 1 año de experiencia.",
    )
    assert result.decision == "APPLY"
    assert result.score >= 75
    assert {"excel", "sql", "pricing"}.issubset(result.matched_skills)
    assert result.positive_reasons


def test_senior_fluent_five_years_is_hard_reject():
    result = evaluate(
        "Senior Data Analyst",
        "SQL y Power BI. Inglés fluido obligatorio. 5 años de experiencia.",
        mode="Remote",
    )
    assert result.decision == "REJECT"
    assert len(result.hard_reject_reasons) == 3


def test_generic_principal_in_junior_description_is_not_a_seniority_reject():
    result = evaluate(
        "Junior Data Analyst",
        "Tu responsabilidad principal será construir dashboards con Power BI.",
    )
    assert not any("Senioridad" in reason for reason in result.hard_reject_reasons)


def test_score_thresholds_are_respected():
    result = evaluate("Unrelated Junior", "Sin habilidades", location="Mars", mode="Onsite")
    assert result.score < 55
    assert result.decision == "REJECT"


def test_explicitly_allowed_senior_is_not_rejected_for_seniority():
    from dataclasses import replace

    profile = replace(PROFILE, allowed_seniority=[*PROFILE.allowed_seniority, "senior"])
    job = Job("Senior Data Analyst", "Test", "Remote", "Remote", "SQL", "test", "https://example.com/s")
    result = score_job(normalize_job(job, profile.skills), profile)
    assert not any("Senioridad" in reason for reason in result.hard_reject_reasons)


def test_spanish_role_matches_with_junior_between_role_tokens():
    from dataclasses import replace

    profile = replace(PROFILE, target_roles=[*PROFILE.target_roles, "analista de pricing"])
    job = Job(
        "Analista Junior Pricing & Marketplace", "Test", "Buenos Aires", "Hybrid",
        "Excel y pricing", "test", "https://example.com/pricing",
    )
    result = score_job(normalize_job(job, profile.skills), profile)
    assert "El puesto coincide con un rol objetivo" in result.positive_reasons
