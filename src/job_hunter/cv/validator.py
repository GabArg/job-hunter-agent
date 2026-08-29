from __future__ import annotations

from .models import AdaptedCV, FactualText, MasterCV, MetricFact
from .rewriter import rewrite_fact
from .summary import RuleBasedSummaryComposer


class CVValidationError(ValueError):
    pass


def validate_cv(cv: AdaptedCV, master: MasterCV) -> None:
    errors: list[str] = []
    valid_factual_ids = master.factual_ids
    companies = {entry.company for entry in master.experience}
    institutions = {entry.institution for entry in [*master.education, *master.courses]}
    technologies = {
        technology for entry in [*master.experience, *master.projects] for technology in entry.technologies
    }
    allowed_skills = set(master.all_skills) | technologies
    all_bullets = [
        bullet for section in [*cv.experience_sections, *cv.project_sections] for bullet in section.bullets
    ]
    for bullet in all_bullets:
        if not bullet.source_fact_ids:
            errors.append(f"Bullet has no source_fact_ids: {bullet.text}")
            continue
        if not set(bullet.source_fact_ids) <= valid_factual_ids:
            errors.append(f"Bullet references invalid facts: {bullet.source_fact_ids}")
            continue
        allowed_texts = [rewrite_fact(master.fact_index[identifier]) for identifier in bullet.source_fact_ids]
        if bullet.text not in allowed_texts:
            errors.append(f"Bullet is not an approved factual rewrite: {bullet.text}")
    if not cv.professional_summary_source_fact_ids:
        errors.append("Summary has no source_fact_ids")
    elif not set(cv.professional_summary_source_fact_ids) <= valid_factual_ids:
        errors.append("Summary references invalid facts")
    else:
        source_facts = [master.fact_index[identifier] for identifier in cv.professional_summary_source_fact_ids]
        expected, expected_ids = RuleBasedSummaryComposer().compose(source_facts)
        if cv.professional_summary != expected:
            errors.append("Summary is not the approved factual composition")
        if cv.professional_summary_source_fact_ids != expected_ids:
            errors.append("Summary source IDs do not match the approved composition")
    if any(section.company not in companies for section in cv.experience_sections):
        errors.append("CV contains a company absent from master CV")
    if any(entry.institution not in institutions for entry in cv.education):
        errors.append("CV contains an institution absent from master CV")
    used_technologies = {
        technology for section in [*cv.experience_sections, *cv.project_sections]
        for technology in section.technologies
    }
    if not used_technologies <= technologies:
        errors.append("CV contains technologies absent from master CV")
    if not set(cv.skills) <= allowed_skills:
        errors.append("CV contains skills absent from configured skills or factual technologies")
    cv.validation_errors = errors
    cv.validation_status = "VALID" if not errors else "INVALID"
    if errors:
        raise CVValidationError("; ".join(errors))


def is_factual_source(value: object) -> bool:
    return isinstance(value, (FactualText, MetricFact))
