from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

from ..models import Job
from .models import MasterCV, SourceFact

ROLE_PRIORITIES = {
    "pricing": ["pricing", "precio", "ventas", "margen", "mercado", "comercial", "excel"],
    "business": ["business", "negocio", "procesos", "process", "kpi", "stakeholder", "decisiones", "operaciones"],
    "operations": ["operations", "operaciones", "procesos", "optimización", "kpi", "automatización", "desvíos"],
    "data": ["data", "datos", "sql", "python", "power bi", "análisis", "métricas", "visualizaciones"],
}


@dataclass(frozen=True, slots=True)
class Selection:
    keywords: list[str]
    summary: list[SourceFact]
    experience_facts: dict[int, list[SourceFact]]
    project_facts: dict[int, list[SourceFact]]
    omitted_ids: list[str]


def extract_job_requirements(job: Job) -> list[str]:
    text = _normalize(f"{job.title} {job.description}")
    family = next((name for name in ("pricing", "business", "operations") if name in text), "data")
    priorities = ROLE_PRIORITIES[family]
    explicit = [keyword for values in ROLE_PRIORITIES.values() for keyword in values if keyword in text]
    return _unique([*priorities, *explicit])[:12]


def select_facts(job: Job, master: MasterCV) -> Selection:
    keywords = extract_job_requirements(job)
    summary = sorted(master.summary_facts, key=lambda fact: relevance_score(fact.text, keywords), reverse=True)[:2]
    experience: dict[int, list[SourceFact]] = {}
    selected_ids = {fact.id for fact in summary}
    for index, entry in enumerate(master.experience):
        candidates = [*entry["fact_objects"], *entry["achievement_objects"]]
        ranked = sorted(candidates, key=lambda fact: (relevance_score(fact.text, keywords), -list(candidates).index(fact)), reverse=True)
        chosen = [fact for fact in ranked if relevance_score(fact.text, keywords) > 0][:3]
        if not chosen and candidates: chosen = candidates[:1]
        experience[index] = chosen
        selected_ids.update(fact.id for fact in chosen)
    projects: dict[int, list[SourceFact]] = {}
    for index, entry in enumerate(master.projects):
        candidates = [*entry["fact_objects"], *entry["metric_objects"]]
        ranked = sorted(candidates, key=lambda fact: (relevance_score(fact.text, keywords), -list(candidates).index(fact)), reverse=True)
        chosen = [fact for fact in ranked if relevance_score(fact.text, keywords) > 0][:2]
        if chosen:
            projects[index] = chosen
            selected_ids.update(fact.id for fact in chosen)
    omitted = [fact_id for fact_id in master.fact_index if fact_id not in selected_ids]
    return Selection(keywords, summary, experience, projects, omitted)


def rank_skills(skills: list[str], keywords: list[str]) -> list[str]:
    return sorted(skills, key=lambda skill: (-relevance_score(skill, keywords), skills.index(skill)))


def relevance_score(text: str, keywords: list[str]) -> int:
    normalized = _normalize(text)
    return sum(1 for keyword in keywords if _normalize(keyword) in normalized)


def _normalize(value: str) -> str:
    value = unicodedata.normalize("NFKD", value.lower())
    return re.sub(r"\s+", " ", "".join(c for c in value if not unicodedata.combining(c)))


def _unique(values: list[str]) -> list[str]:
    return list(dict.fromkeys(values))
