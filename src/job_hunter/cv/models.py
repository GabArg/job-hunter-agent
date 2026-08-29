from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class CVApprovalState(StrEnum):
    NOT_GENERATED = "NOT_GENERATED"
    GENERATED = "GENERATED"
    REVIEWED = "REVIEWED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


@dataclass(frozen=True, slots=True)
class SourceFact:
    id: str
    text: str
    kind: str
    owner_index: int | None = None


@dataclass(slots=True)
class MasterCV:
    personal: dict[str, str]
    summary_facts: list[SourceFact]
    experience: list[dict[str, Any]]
    projects: list[dict[str, Any]]
    education: list[dict[str, str]]
    courses: list[str]
    skills: list[str]
    languages: list[dict[str, str]]
    fact_index: dict[str, SourceFact]


@dataclass(frozen=True, slots=True)
class FactualBullet:
    text: str
    source_fact_ids: list[str]


@dataclass(slots=True)
class ExperienceSection:
    company: str
    role: str
    start_date: str
    end_date: str
    bullets: list[FactualBullet]
    technologies: list[str]


@dataclass(slots=True)
class ProjectSection:
    name: str
    description: str
    bullets: list[FactualBullet]
    technologies: list[str]
    links: list[str]


@dataclass(slots=True)
class AdaptedCV:
    job_id: int | str | None
    job_title: str
    company: str
    match_score: float
    personal: dict[str, str]
    professional_summary: str
    professional_summary_source_fact_ids: list[str]
    experience_sections: list[ExperienceSection]
    project_sections: list[ProjectSection]
    education: list[dict[str, str]]
    skills: list[str]
    languages: list[dict[str, str]]
    selected_keywords: list[str]
    omitted_facts: list[str]
    validation_status: str = "PENDING"
    validation_errors: list[str] = field(default_factory=list)
    approval_state: CVApprovalState = CVApprovalState.GENERATED
