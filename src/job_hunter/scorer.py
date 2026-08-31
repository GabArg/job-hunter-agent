from __future__ import annotations

from .models import Job, Profile, ScoreResult
from .normalizer import normalize_english_level
from .semantics import display_concepts, expand_candidate_capabilities, roles_match

ENGLISH_RANK = {"none": 0, "basic": 1, "intermediate": 2, "upper-intermediate": 3, "advanced": 4, "fluent": 5}
DEFAULT_REJECTED_SENIORITIES = {"senior", "lead", "staff", "principal"}
EMPTY_REASON_VALUES = {"", "-", "—", "none", "n/a", "null", "no"}


def score_job(
    job: Job,
    profile: Profile,
    candidate_capability_evidence: dict[str, list[str]] | None = None,
) -> ScoreResult:
    weights, earned = profile.scoring_weights, 0.0
    positive: list[str] = []; hard_rejects: list[str] = []
    role_match = any(roles_match(job.title, role, job.description) for role in profile.target_roles)
    if role_match:
        earned += weights.get("role", 0); positive.append("El puesto coincide con un rol objetivo")

    requirements = list(dict.fromkeys(job.job_requirements))
    profile_capabilities = expand_candidate_capabilities(profile.skills)
    capability_evidence = {
        concept: [f"profile.skill:{concept}"] for concept in profile_capabilities
    }
    for concept, sources in (candidate_capability_evidence or {}).items():
        current = capability_evidence.setdefault(concept, [])
        current.extend(source for source in sources if source not in current)
    candidate_skills = set(capability_evidence)
    matched = [concept for concept in requirements if concept in candidate_skills]
    missing = [concept for concept in requirements if concept not in candidate_skills]
    # Only requirements present in the offer participate in this component. Profile targets never become gaps.
    skill_ratio = len(matched) / len(requirements) if requirements else 0.0
    earned += weights.get("skills", 0) * skill_ratio
    if matched: positive.append(f"Requisitos coincidentes: {', '.join(display_concepts(matched))}")

    if any(location in job.location for location in profile.preferred_locations):
        earned += weights.get("location", 0); positive.append("Ubicación preferida")
    if job.work_mode in profile.preferred_work_modes:
        earned += weights.get("work_mode", 0); positive.append("Modalidad preferida")
    if any(company.casefold() == job.company.casefold() for company in profile.preferred_companies):
        # Deliberately small: preference improves ordering but cannot justify APPLY alone.
        earned += min(2.0, weights.get("role", 0) * 0.07)
        positive.append("Empresa preferida")
    if job.seniority is None or job.seniority in profile.allowed_seniority:
        earned += weights.get("seniority", 0); positive.append("Senioridad compatible")

    rules = profile.hard_reject_rules
    if rules.get("reject_unlisted_seniority", True) and job.seniority in DEFAULT_REJECTED_SENIORITIES and job.seniority not in profile.allowed_seniority:
        hard_rejects.append(f"Senioridad no permitida: {job.seniority}")
    if rules.get("reject_excess_experience", True) and job.required_years is not None and job.required_years > profile.max_required_years:
        hard_rejects.append(f"Experiencia requerida ({job.required_years:g} años) supera el máximo ({profile.max_required_years:g})")
    if rules.get("reject_insufficient_english", True) and job.required_english:
        required = normalize_english_level(job.required_english)
        candidate = normalize_english_level(profile.english_level)
        if ENGLISH_RANK.get(required, 0) > ENGLISH_RANK.get(candidate, 0):
            hard_rejects.append(f"Nivel de inglés requerido ({required}) supera el nivel del candidato ({candidate})")

    hard_rejects = normalize_reason_list(hard_rejects)
    score = round(max(0.0, min(100.0, earned / (sum(weights.values()) or 1.0) * 100)), 2)
    decision = "REJECT" if hard_rejects or score < 55 else "APPLY" if score >= 75 else "REVIEW"
    target_terms = list(dict.fromkeys([*profile.target_roles, *profile.skills]))
    matched_evidence = {concept: capability_evidence[concept] for concept in matched}
    return ScoreResult(score, decision, matched, missing, hard_rejects, positive, requirements, matched,
                       sorted(candidate_skills), target_terms, matched_evidence)


def normalize_reason_list(values) -> list[str]:
    if not values: return []
    return [str(value).strip() for value in values if str(value).strip().casefold() not in EMPTY_REASON_VALUES]


def _role_matches(title: str, target_role: str) -> bool:
    """Backward-compatible wrapper for older callers/tests."""
    return roles_match(title, target_role)
