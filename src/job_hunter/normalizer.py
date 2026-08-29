from __future__ import annotations

import re
import unicodedata

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
ENGLISH_PATTERNS = {
    "c2": r"\bc2\b",
    "c1": r"\bc1\b",
    "fluent": r"\b(?:fluent|fluido|bilingual|bilingue)\b",
    "advanced": r"\b(?:advanced|avanzado)\b",
    "intermediate": r"\b(?:intermediate|intermedio|b2)\b",
    "basic": r"\b(?:basic|basico|básico|a1|a2)\b",
}


def clean_text(value: str) -> str:
    value = unicodedata.normalize("NFKC", value or "").strip().lower()
    return re.sub(r"\s+", " ", value)


def normalize_job(job: Job, known_skills: list[str] | None = None) -> Job:
    job.title = clean_text(job.title)
    job.company = (job.company or "").strip()
    job.location = clean_text(job.location)
    job.work_mode = _normalize_work_mode(job.work_mode)
    job.description = re.sub(r"\s+", " ", (job.description or "").strip())
    job.source = clean_text(job.source)
    job.url = (job.url or "").strip()
    searchable = clean_text(f"{job.title} {job.description}")
    job.seniority = _first_match(searchable, SENIORITY_PATTERNS)
    job.required_english = _extract_english(searchable)
    job.required_years = _extract_years(searchable)
    job.job_requirements = detect_concepts(job.description)
    candidate_concepts = canonicalize_terms(known_skills or [])
    job.detected_skills = [concept for concept in job.job_requirements if concept in candidate_concepts]
    roles = detect_roles(job.title, job.description)
    subtypes = [role for role in roles if role.startswith("business-analyst-")]
    job.role_subtype = sorted(subtypes)[0] if subtypes else (sorted(roles)[0] if roles else None)
    return job


def _normalize_work_mode(value: str) -> str:
    value = clean_text(value)
    aliases = {
        "remoto": "remote",
        "remote": "remote",
        "hibrido": "hybrid",
        "híbrido": "hybrid",
        "hybrid": "hybrid",
        "presencial": "onsite",
        "on-site": "onsite",
        "onsite": "onsite",
    }
    return aliases.get(value, value)


def _first_match(text: str, patterns: dict[str, str]) -> str | None:
    return next((name for name, pattern in patterns.items() if re.search(pattern, text)), None)


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
    language = r"(?:ingles|inglés|english)"
    for level, pattern in ENGLISH_PATTERNS.items():
        if re.search(rf"{language}.{{0,30}}{pattern}|{pattern}.{{0,20}}{language}", text):
            return level
    return None


def _contains_term(text: str, term: str) -> bool:
    return bool(re.search(rf"(?<!\w){re.escape(term)}(?!\w)", text))
