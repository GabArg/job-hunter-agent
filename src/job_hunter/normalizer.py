from __future__ import annotations

import re
import unicodedata

from .models import Job

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
    job.required_english = _first_match(searchable, ENGLISH_PATTERNS)
    job.required_years = _extract_years(searchable)
    job.detected_skills = [
        skill for skill in (known_skills or []) if _contains_term(searchable, clean_text(skill))
    ]
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
        r"(?:mas de |más de |minimo |mínimo |al menos )?(\d+(?:[.,]\d+)?)\s*(?:\+\s*)?(?:anos|años|years?)",
        r"(?:experiencia de|required experience(?: of)?)\s*(\d+(?:[.,]\d+)?)",
    )
    values = [
        float(match.replace(",", "."))
        for pattern in patterns
        for match in re.findall(pattern, text)
    ]
    return max(values) if values else None


def _contains_term(text: str, term: str) -> bool:
    return bool(re.search(rf"(?<!\w){re.escape(term)}(?!\w)", text))
