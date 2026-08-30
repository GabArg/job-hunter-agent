from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import replace

from ..models import Job
from .models import AdaptedCV, CourseEntry, ExperienceSection, FactualBullet, FactualText, MasterCV, ProjectSection
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
        return self.summary_composer.compose(selection.summary, selection.keywords)


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
        projects, list(master.education), [_informative_course_label(master.courses[index], selection)
                                          for index in selection.course_indices],
        select_skills(job, master, selection, 12 if content_mode == "concise" else 18),
        list(master.languages), selection.keywords, selection.omitted_ids, content_mode,
    )
    validate_cv(cv, master)
    return cv


def _informative_course_label(course: CourseEntry, selection: Selection) -> CourseEntry:
    """Replace vague program labels using only topic names present in factual course text."""
    if course.program.casefold() not in {"formación continua en datos", "datos y tecnología"}:
        return course
    factual_text = " ".join(fact.text for fact in course.facts).casefold()
    topics = (
        "SQL", "Python", "Power BI", "Data Analytics", "Business Intelligence", "Reporting",
        "Pandas", "PostgreSQL", "DAX", "Machine Learning", "APIs REST", "JSON", "JSONL",
    )
    relevant = [topic for topic in topics if topic.casefold() in factual_text]
    keyword_text = " ".join(selection.keywords).replace("-", " ").casefold()
    requested = [topic for topic in relevant if topic.casefold() in keyword_text]
    chosen = (requested + [topic for topic in relevant if topic not in requested])[:3]
    return replace(course, program=" / ".join(chosen)) if chosen else course
