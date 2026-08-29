from __future__ import annotations

from .models import Job, Profile, ScoreResult

ENGLISH_RANK = {
    "none": 0,
    "basic": 1,
    "intermediate": 2,
    "advanced": 3,
    "fluent": 4,
    "c1": 4,
    "c2": 5,
}
DEFAULT_REJECTED_SENIORITIES = {"senior", "lead", "staff", "principal"}


def score_job(job: Job, profile: Profile) -> ScoreResult:
    weights = profile.scoring_weights
    earned = 0.0
    positive: list[str] = []
    hard_rejects: list[str] = []

    role_match = any(role in job.title for role in profile.target_roles)
    if role_match:
        earned += weights.get("role", 0)
        positive.append("El puesto coincide con un rol objetivo")

    matched = [skill for skill in profile.skills if skill in job.detected_skills]
    missing = [skill for skill in profile.skills if skill not in matched]
    skill_ratio = len(matched) / len(profile.skills) if profile.skills else 1.0
    earned += weights.get("skills", 0) * skill_ratio
    if matched:
        positive.append(f"Habilidades coincidentes: {', '.join(matched)}")

    if any(location in job.location for location in profile.preferred_locations):
        earned += weights.get("location", 0)
        positive.append("Ubicación preferida")
    if job.work_mode in profile.preferred_work_modes:
        earned += weights.get("work_mode", 0)
        positive.append("Modalidad preferida")
    if job.seniority is None or job.seniority in profile.allowed_seniority:
        earned += weights.get("seniority", 0)
        positive.append("Senioridad compatible")

    rules = profile.hard_reject_rules
    if rules.get("reject_unlisted_seniority", True):
        if job.seniority in DEFAULT_REJECTED_SENIORITIES and job.seniority not in profile.allowed_seniority:
            hard_rejects.append(f"Senioridad no permitida: {job.seniority}")
    if rules.get("reject_excess_experience", True):
        if job.required_years is not None and job.required_years > profile.max_required_years:
            hard_rejects.append(
                f"Experiencia requerida ({job.required_years:g} años) supera el máximo ({profile.max_required_years:g})"
            )
    if rules.get("reject_insufficient_english", True) and job.required_english:
        required_rank = ENGLISH_RANK.get(job.required_english, 0)
        profile_rank = ENGLISH_RANK.get(profile.english_level, 0)
        if required_rank >= ENGLISH_RANK["advanced"] and profile_rank < required_rank:
            hard_rejects.append(
                f"Inglés requerido ({job.required_english}) supera el nivel del perfil ({profile.english_level})"
            )

    total_weight = sum(weights.values()) or 1.0
    score = round(max(0.0, min(100.0, earned / total_weight * 100)), 2)
    if hard_rejects or score < 55:
        decision = "REJECT"
    elif score >= 75:
        decision = "APPLY"
    else:
        decision = "REVIEW"
    return ScoreResult(score, decision, matched, missing, hard_rejects, positive)
