from __future__ import annotations

import re
import unicodedata
from typing import Any

from .models import Job
from .semantics import canonicalize_terms, detect_concepts, detect_roles

SENIORITY_PATTERNS = {
    "principal": r"\bprincipal\b",
    "staff": r"\bstaff\b",
    "lead": r"\b(?:lead|lider|líder)\b",
    "semi-senior": r"\b(?:semi[ -]?senior|ssr\.?)\b",
    "senior": r"\b(?:senior|sr\.?)\b",
    "junior": r"\b(?:junior|jr\.?)\b",
}
ROLE_PATTERN = (
    r"(?:data\s+)?(?:analyst|analista|scientist|cientifico|cientifica|engineer|ingeniero|ingeniera|"
    r"consultant|consultor|consultora|developer|desarrollador|desarrolladora|architect|arquitecto|"
    r"arquitecta|specialist|especialista)"
)
ENGLISH_PATTERNS = {
    "fluent": r"\b(?:c2|fluent|fluido|bilingual|bilingue|native|nativo)\b",
    "advanced": r"\b(?:c1|advanced|avanzado|excellent|excelente|professional working proficiency|full professional proficiency)\b",
    "upper-intermediate": r"\b(?:b2|upper[ -]intermediate|intermedio alto)\b",
    "intermediate": r"\b(?:b1|intermediate|intermedio)\b",
    "basic": r"\b(?:a1|a2|basic|basico)\b",
}
MANDATORY_ENGLISH_SIGNALS = (
    "required", "mandatory", "must have", "must", "essential", "excluyente", "requisito",
    "indispensable", "necesario", "necesaria", "obligatorio", "obligatoria",
)
DESIRABLE_ENGLISH_SIGNALS = (
    "preferred", "nice to have", "desirable", "plus", "valued", "se valora", "deseable",
)


def clean_text(value: str) -> str:
    value = unicodedata.normalize("NFKC", value or "").strip().lower()
    return re.sub(r"\s+", " ", value)


def normalize_job(job: Job, known_skills: list[str] | None = None) -> Job:
    job.title = clean_text(job.title)
    job.company = (job.company or "").strip()
    job.location = clean_text(job.location)
    job.work_mode = normalize_work_mode(job.work_mode, job.description, job.raw_data)
    job.description = re.sub(r"\s+", " ", (job.description or "").strip())
    job.source = clean_text(job.source)
    job.url = (job.url or "").strip()
    searchable = clean_text(f"{job.title} {job.description}")
    title_seniority = _extract_role_seniority(job.title)
    description_seniority = _extract_role_seniority(clean_text(job.description))
    job.seniority = title_seniority or description_seniority
    job.seniority_evidence = {
        "title": title_seniority,
        "description": description_seniority,
        "conflict": bool(title_seniority and description_seniority and title_seniority != description_seniority),
    }
    job.required_english = _extract_english(searchable)
    job.required_years = _extract_years(searchable)
    job.job_requirements = detect_concepts(job.description)
    candidate_concepts = canonicalize_terms(known_skills or [])
    job.detected_skills = [concept for concept in job.job_requirements if concept in candidate_concepts]
    roles = detect_roles(job.title, job.description)
    subtypes = [role for role in roles if role.startswith("business-analyst-")]
    job.role_subtype = sorted(subtypes)[0] if subtypes else (sorted(roles)[0] if roles else None)
    return job


VALID_WORK_MODES = {"remote", "hybrid", "onsite", "unknown"}


def normalize_work_mode(value: Any, description: str = "", raw_data: Any = None) -> str:
    """Return modality only; employment types such as full-time are ignored."""
    evidence = " ".join(part for part in (_work_mode_text(value), description, _work_mode_text(raw_data)) if part)
    text = clean_text(evidence)
    signals = {
        "hybrid": ("hybrid", "hibrido", "híbrido", "hibrida", "híbrida", "modalidad mixta"),
        "remote": ("remote", "remoto", "remota", "home office", "work from home"),
        "onsite": ("onsite", "on-site", "on site", "presencial", "in-office", "in office"),
    }
    for mode, aliases in signals.items():
        if any(re.search(rf"(?<!\w){re.escape(clean_text(alias))}(?!\w)", text) for alias in aliases):
            return mode
    return "unknown"


def _work_mode_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        return " ".join(_work_mode_text(child) for child in value.values())
    if isinstance(value, (list, tuple, set)):
        return " ".join(_work_mode_text(child) for child in value)
    return ""


def _normalize_work_mode(value: Any) -> str:
    """Backward-compatible wrapper."""
    return normalize_work_mode(value)


def _first_match(text: str, patterns: dict[str, str]) -> str | None:
    return next((name for name, pattern in patterns.items() if re.search(pattern, text)), None)


def _extract_role_seniority(text: str) -> str | None:
    """Extract seniority only when it is syntactically attached to a role."""
    folded = _fold(text)
    for name, seniority_pattern in SENIORITY_PATTERNS.items():
        token = rf"(?:{seniority_pattern})"
        patterns = (
            rf"{token}(?:[ -]level)?(?:\s+\w+){{0,3}}\s+{ROLE_PATTERN}\b",
            rf"\b{ROLE_PATTERN}\b(?:\s+(?:de|of)\s+\w+|\s+\w+){{0,3}}\s*(?:[,\-/]\s*)?{token}",
        )
        for pattern in patterns:
            match = re.search(pattern, folded)
            if match and not (name == "lead" and re.search(r"\blead\s+generation\b", match.group())):
                return name
    return None


def _extract_years(text: str) -> float | None:
    patterns = (
        r"(?:experiencia de|required experience(?: of)?|minimum|minimo|mínimo|al menos)\s*(\d+(?:[.,]\d+)?)\s*(?:\+\s*)?(?:anos|años|years?)?",
        r"(\d+(?:[.,]\d+)?)\s*(?:\+\s*)?(?:anos|años|years?)\s+de experiencia(?:\s+(?:en|como|con)\b|\s*[.,;]|$)",
    )
    values = [
        float(match.replace(",", "."))
        for pattern in patterns
        for match in re.findall(pattern, text)
    ]
    return max(values) if values else None


def _extract_english(text: str) -> str | None:
    folded = _fold(text)
    language_matches = list(re.finditer(r"\b(?:ingles|english)\b", folded))
    candidates: list[tuple[bool, bool, int, str]] = []
    for level, pattern in ENGLISH_PATTERNS.items():
        for level_match in re.finditer(pattern, folded):
            for language_match in language_matches:
                distance = max(language_match.start(), level_match.start()) - min(language_match.end(), level_match.end())
                if distance > 55: continue
                start = max(0, min(language_match.start(), level_match.start()) - 45)
                end = min(len(folded), max(language_match.end(), level_match.end()) + 45)
                context = folded[start:end]
                mandatory = any(_contains_term(context, signal) for signal in MANDATORY_ENGLISH_SIGNALS)
                desirable = any(_contains_term(context, signal) for signal in DESIRABLE_ENGLISH_SIGNALS)
                candidates.append((mandatory, desirable, start, level))
    required = [candidate for candidate in candidates if candidate[0]]
    if required: return required[0][3]
    neutral = [candidate for candidate in candidates if not candidate[1]]
    if neutral: return neutral[0][3]
    return None


def normalize_english_level(value: str | None) -> str:
    folded = _fold(value or "none")
    for level, pattern in ENGLISH_PATTERNS.items():
        if re.search(pattern, folded): return level
    return "none" if folded in {"", "none", "ninguno"} else folded.replace(" ", "-")


def _fold(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value.casefold())
    return re.sub(r"\s+", " ", "".join(character for character in normalized if not unicodedata.combining(character)))


def _contains_term(text: str, term: str) -> bool:
    return bool(re.search(rf"(?<!\w){re.escape(term)}(?!\w)", text))
