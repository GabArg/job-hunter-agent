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
class FactualText:
    id: str
    text: str
    tags: tuple[str, ...] = ()
    kind: str = "fact"
    owner_id: str | None = None


@dataclass(frozen=True, slots=True)
class MetricFact(FactualText):
    kind: str = "metric"


# Backward-compatible public name used by existing integrations.
SourceFact = FactualText


@dataclass(slots=True)
class ExperienceEntry:
    id: str
    company: str
    role: str
    start_date: str
    end_date: str
    location: str
    facts: list[FactualText]
    technologies: list[str]
    achievements: list[FactualText] = field(default_factory=list)


@dataclass(slots=True)
class ProjectEntry:
    id: str
    name: str
    category: str
    facts: list[FactualText]
    metrics: list[MetricFact]
    technologies: list[str]
    links: list[str]


@dataclass(slots=True)
class EducationEntry:
    id: str
    institution: str
    program: str
    status: str
    dates: str = ""
    facts: list[FactualText] = field(default_factory=list)


@dataclass(slots=True)
class CourseEntry:
    id: str
    institution: str
    program: str
    status: str
    facts: list[FactualText] = field(default_factory=list)


@dataclass(slots=True)
class LanguageEntry:
    id: str
    language: str
    level: str
    facts: list[FactualText] = field(default_factory=list)


@dataclass(slots=True)
class MasterCV:
    personal: dict[str, str]
    summary_facts: list[FactualText]
    experience: list[ExperienceEntry]
    projects: list[ProjectEntry]
    education: list[EducationEntry]
    courses: list[CourseEntry]
    skills_by_category: dict[str, list[str]]
    all_skills: list[str]
    languages: list[LanguageEntry]
    metadata: dict[str, Any]
    fact_index: dict[str, object]

    @property
    def skills(self) -> list[str]:
        return self.all_skills

    @property
    def factual_ids(self) -> set[str]:
        return {
            identifier for identifier, value in self.fact_index.items()
            if isinstance(value, (FactualText, MetricFact))
        }


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
    education: list[EducationEntry]
    skills: list[str]
    languages: list[LanguageEntry]
    selected_keywords: list[str]
    omitted_facts: list[str]
    content_mode: str = "concise"
    validation_status: str = "PENDING"
    validation_errors: list[str] = field(default_factory=list)
    approval_state: CVApprovalState = CVApprovalState.GENERATED
