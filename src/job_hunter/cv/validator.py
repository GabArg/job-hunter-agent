from __future__ import annotations

from .models import AdaptedCV, MasterCV


class CVValidationError(ValueError):
    pass


def validate_cv(cv: AdaptedCV, master: MasterCV) -> None:
    errors: list[str] = []
    valid_ids = set(master.fact_index)
    companies = {str(entry["company"]) for entry in master.experience}
    technologies = {
        str(value) for entry in [*master.experience, *master.projects]
        for value in entry.get("technologies", [])
    }
    all_bullets = [
        bullet for section in [*cv.experience_sections, *cv.project_sections] for bullet in section.bullets
    ]
    for bullet in all_bullets:
        if not bullet.source_fact_ids:
            errors.append(f"Bullet has no source_fact_ids: {bullet.text}")
            continue
        if not set(bullet.source_fact_ids) <= valid_ids:
            errors.append(f"Bullet references invalid facts: {bullet.source_fact_ids}")
            continue
        source_texts = [master.fact_index[fact_id].text for fact_id in bullet.source_fact_ids]
        if bullet.text not in source_texts:
            errors.append(f"Rule-based bullet differs from source fact: {bullet.text}")
    if not set(cv.professional_summary_source_fact_ids) <= valid_ids:
        errors.append("Summary references invalid facts")
    expected_summary = " ".join(master.fact_index[fact_id].text for fact_id in cv.professional_summary_source_fact_ids)
    if cv.professional_summary != expected_summary:
        errors.append("Summary contains content not present in its source facts")
    if any(section.company not in companies for section in cv.experience_sections):
        errors.append("CV contains a company absent from master CV")
    used_technologies = {
        technology for section in [*cv.experience_sections, *cv.project_sections]
        for technology in section.technologies
    }
    if not used_technologies <= technologies:
        errors.append("CV contains technologies absent from master CV")
    cv.validation_errors = errors
    cv.validation_status = "VALID" if not errors else "INVALID"
    if errors:
        raise CVValidationError("; ".join(errors))
