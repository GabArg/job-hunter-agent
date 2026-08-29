from __future__ import annotations

from abc import ABC, abstractmethod

from ..models import Job
from .models import AdaptedCV, ExperienceSection, FactualBullet, FactualText, MasterCV, ProjectSection
from .rewriter import rewrite_fact
from .selector import Selection, rank_skills, relevance_score, select_facts, select_skills
from .summary import RuleBasedSummaryComposer, SummaryComposer
from .validator import validate_cv


class CVTextGenerator(ABC):
    @abstractmethod
    def bullet(self, fact: FactualText) -> FactualBullet: ...

    @abstractmethod
    def summary(self, selection: Selection) -> tuple[str, list[str]]: ...


class RuleBasedCVTextGenerator(CVTextGenerator):
    def __init__(self, summary_composer: SummaryComposer | None = None):
        self.summary_composer = summary_composer or RuleBasedSummaryComposer()

    def bullet(self, fact: FactualText) -> FactualBullet:
        return FactualBullet(text=rewrite_fact(fact), source_fact_ids=[fact.id])

    def summary(self, selection: Selection) -> tuple[str, list[str]]:
        return self.summary_composer.compose(selection.summary)


class LLMCVTextGenerator(CVTextGenerator):
    """Future extension point; requires a factual constrained implementation."""

    def bullet(self, fact: FactualText) -> FactualBullet:
        raise NotImplementedError("LLM CV generation is not configured")

    def summary(self, selection: Selection) -> tuple[str, list[str]]:
        raise NotImplementedError("LLM CV generation is not configured")


def adapt_cv(
    job: Job,
    master: MasterCV,
    generator: CVTextGenerator | None = None,
    allow_reject: bool = False,
    content_mode: str = "concise",
) -> AdaptedCV:
    if job.decision == "REJECT" and not allow_reject:
        raise ValueError("CV generation is disabled for REJECT jobs; use an explicit override")
    if job.decision not in {"APPLY", "REVIEW", "REJECT"}:
        raise ValueError("Job must be scored before CV generation")
    text_generator = generator or RuleBasedCVTextGenerator()
    selection = select_facts(job, master, content_mode)
    summary, summary_ids = text_generator.summary(selection)
    experiences = []
    for index, entry in enumerate(master.experience):
        facts = selection.experience_facts.get(index, [])
        if not facts: continue
        relevance = relevance_score(
            " ".join([*(fact.text for fact in facts), *entry.technologies]),
            selection.keywords,
        )
        experiences.append((relevance, index, ExperienceSection(
            entry.company, entry.role, entry.start_date, entry.end_date,
            [text_generator.bullet(fact) for fact in facts],
            rank_skills(entry.technologies, selection.keywords),
        )))
    projects = []
    for index, facts in selection.project_facts.items():
        entry = master.projects[index]
        projects.append(ProjectSection(
            entry.name, entry.category,
            [text_generator.bullet(fact) for fact in facts],
            rank_skills(entry.technologies, selection.keywords), entry.links,
        ))
    cv = AdaptedCV(
        job.id or job.url, job.title, job.company, float(job.score or 0), dict(master.personal),
        summary, summary_ids,
        [section for _, _, section in sorted(experiences, key=lambda item: (-item[0], item[1]))],
        projects, list(master.education), select_skills(job, master, selection, 12 if content_mode == "concise" else 18),
        list(master.languages), selection.keywords, selection.omitted_ids, content_mode,
    )
    validate_cv(cv, master)
    return cv
