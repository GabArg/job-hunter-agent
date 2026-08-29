from __future__ import annotations

from abc import ABC, abstractmethod

from ..models import Job
from .models import AdaptedCV, ExperienceSection, FactualBullet, MasterCV, ProjectSection
from .selector import Selection, rank_skills, relevance_score, select_facts
from .validator import validate_cv


class CVTextGenerator(ABC):
    @abstractmethod
    def bullet(self, text: str, source_fact_ids: list[str]) -> FactualBullet: ...

    @abstractmethod
    def summary(self, selection: Selection) -> tuple[str, list[str]]: ...


class RuleBasedCVTextGenerator(CVTextGenerator):
    def bullet(self, text: str, source_fact_ids: list[str]) -> FactualBullet:
        return FactualBullet(text=text, source_fact_ids=source_fact_ids)

    def summary(self, selection: Selection) -> tuple[str, list[str]]:
        return " ".join(fact.text for fact in selection.summary), [fact.id for fact in selection.summary]


class LLMCVTextGenerator(CVTextGenerator):
    """Future extension point; requires a factual constrained implementation."""

    def bullet(self, text: str, source_fact_ids: list[str]) -> FactualBullet:
        raise NotImplementedError("LLM CV generation is not configured")

    def summary(self, selection: Selection) -> tuple[str, list[str]]:
        raise NotImplementedError("LLM CV generation is not configured")


def adapt_cv(
    job: Job,
    master: MasterCV,
    generator: CVTextGenerator | None = None,
    allow_reject: bool = False,
) -> AdaptedCV:
    if job.decision == "REJECT" and not allow_reject:
        raise ValueError("CV generation is disabled for REJECT jobs; use an explicit override")
    if job.decision not in {"APPLY", "REVIEW", "REJECT"}:
        raise ValueError("Job must be scored before CV generation")
    text_generator = generator or RuleBasedCVTextGenerator()
    selection = select_facts(job, master)
    summary, summary_ids = text_generator.summary(selection)
    experiences = []
    for index, entry in enumerate(master.experience):
        facts = selection.experience_facts.get(index, [])
        if not facts: continue
        relevance = relevance_score(
            " ".join([*(fact.text for fact in facts), *(str(value) for value in entry.get("technologies", []))]),
            selection.keywords,
        )
        experiences.append((relevance, index, ExperienceSection(
            str(entry["company"]), str(entry["role"]), str(entry["start_date"]), str(entry["end_date"]),
            [text_generator.bullet(fact.text, [fact.id]) for fact in facts],
            rank_skills([str(value) for value in entry.get("technologies", [])], selection.keywords),
        )))
    projects = []
    for index, facts in selection.project_facts.items():
        entry = master.projects[index]
        projects.append(ProjectSection(
            str(entry["name"]), str(entry.get("description", "")),
            [text_generator.bullet(fact.text, [fact.id]) for fact in facts],
            rank_skills([str(value) for value in entry.get("technologies", [])], selection.keywords),
            [str(value) for value in entry.get("links", [])],
        ))
    cv = AdaptedCV(
        job.id or job.url, job.title, job.company, float(job.score or 0), dict(master.personal),
        summary, summary_ids,
        [section for _, _, section in sorted(experiences, key=lambda item: (-item[0], item[1]))],
        projects, list(master.education), rank_skills(master.skills, selection.keywords),
        list(master.languages), selection.keywords, selection.omitted_ids,
    )
    validate_cv(cv, master)
    return cv
