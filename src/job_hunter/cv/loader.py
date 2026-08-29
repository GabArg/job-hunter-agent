from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from .models import (
    CourseEntry, EducationEntry, ExperienceEntry, FactualText, LanguageEntry,
    MasterCV, MetricFact, ProjectEntry,
)

REQUIRED = {"personal", "summary_facts", "experience", "projects", "education", "skills", "languages"}


def load_candidate_profile(path: str | Path) -> dict[str, Any]:
    with Path(path).open(encoding="utf-8") as handle:
        data = yaml.safe_load(handle) or {}
    if not isinstance(data, dict):
        raise ValueError("Candidate profile must be a YAML mapping")
    return data


def load_master_cv(path: str | Path) -> MasterCV:
    with Path(path).open(encoding="utf-8") as handle:
        data: dict[str, Any] = yaml.safe_load(handle) or {}
    missing = REQUIRED - data.keys()
    if missing:
        raise ValueError(f"Master CV is missing keys: {', '.join(sorted(missing))}")
    index: dict[str, object] = {}
    summary = _facts(data["summary_facts"], "summary", None, index)
    experience = [_experience(entry, number, index) for number, entry in enumerate(data["experience"], 1)]
    projects = [_project(entry, number, index) for number, entry in enumerate(data["projects"], 1)]
    education = [_education(entry, number, index) for number, entry in enumerate(data["education"], 1)]
    courses = [_course(entry, number, index) for number, entry in enumerate(data.get("courses", []), 1)]
    languages = [_language(entry, number, index) for number, entry in enumerate(data["languages"], 1)]
    skills_by_category = _skills(data["skills"])
    return MasterCV(
        personal={str(key): str(value) for key, value in data["personal"].items()},
        summary_facts=summary, experience=experience, projects=projects, education=education,
        courses=courses, skills_by_category=skills_by_category,
        all_skills=_unique(skill for values in skills_by_category.values() for skill in values),
        languages=languages, metadata=dict(data.get("metadata") or {}), fact_index=index,
    )


def _experience(entry, number: int, index: dict[str, object]) -> ExperienceEntry:
    identifier = str(entry.get("id") or f"exp_{number:02d}")
    result = ExperienceEntry(
        identifier, str(entry["company"]), str(entry["role"]), str(entry["start_date"]),
        str(entry["end_date"]), str(entry.get("location", "")),
        _facts(entry.get("facts", []), f"{identifier}_fact", identifier, index),
        [str(value) for value in entry.get("technologies", [])],
        _facts(entry.get("achievements", []), f"{identifier}_achievement", identifier, index),
    )
    _register(identifier, result, index)
    return result


def _project(entry, number: int, index: dict[str, object]) -> ProjectEntry:
    identifier = str(entry.get("id") or f"project_{number:02d}")
    result = ProjectEntry(
        identifier, str(entry["name"]), str(entry.get("category") or entry.get("description", "")),
        _facts(entry.get("facts", []), f"{identifier}_fact", identifier, index),
        _metrics(entry.get("metrics", []), f"{identifier}_metric", identifier, index),
        [str(value) for value in entry.get("technologies", [])],
        [str(value) for value in entry.get("links", [])],
    )
    _register(identifier, result, index)
    return result


def _education(entry, number: int, index: dict[str, object]) -> EducationEntry:
    identifier = str(entry.get("id") or f"edu_{number:02d}")
    result = EducationEntry(
        identifier, str(entry["institution"]), str(entry["program"]), str(entry["status"]),
        str(entry.get("dates", "")), _facts(entry.get("facts", []), f"{identifier}_fact", identifier, index),
    )
    _register(identifier, result, index)
    return result


def _course(entry, number: int, index: dict[str, object]) -> CourseEntry:
    if not isinstance(entry, dict):
        entry = {"program": str(entry), "institution": "", "status": ""}
    identifier = str(entry.get("id") or f"course_{number:02d}")
    result = CourseEntry(
        identifier, str(entry.get("institution", "")), str(entry.get("program", "")),
        str(entry.get("status", "")), _facts(entry.get("facts", []), f"{identifier}_fact", identifier, index),
    )
    _register(identifier, result, index)
    return result


def _language(entry, number: int, index: dict[str, object]) -> LanguageEntry:
    identifier = str(entry.get("id") or f"lang_{number:02d}")
    result = LanguageEntry(
        identifier, str(entry["language"]), str(entry["level"]),
        _facts(entry.get("facts", []), f"{identifier}_fact", identifier, index),
    )
    _register(identifier, result, index)
    return result


def _facts(values, prefix: str, owner_id: str | None, index: dict[str, object]) -> list[FactualText]:
    results = []
    for number, value in enumerate(values, 1):
        if isinstance(value, dict):
            identifier, text = str(value.get("id") or f"{prefix}_{number:02d}"), str(value["text"])
            tags = tuple(str(tag) for tag in value.get("tags", []))
        else:
            identifier, text, tags = f"{prefix}_{number:02d}", str(value), ()
        fact = FactualText(identifier, text, tags, prefix, owner_id)
        _register(identifier, fact, index)
        results.append(fact)
    return results


def _metrics(values, prefix: str, owner_id: str, index: dict[str, object]) -> list[MetricFact]:
    results = []
    for number, value in enumerate(values, 1):
        if isinstance(value, dict):
            identifier, text = str(value.get("id") or f"{prefix}_{number:02d}"), str(value["text"])
            tags = tuple(str(tag) for tag in value.get("tags", []))
        else:
            identifier, text, tags = f"{prefix}_{number:02d}", str(value), ()
        fact = MetricFact(identifier, text, tags, owner_id=owner_id)
        _register(identifier, fact, index)
        results.append(fact)
    return results


def _skills(value) -> dict[str, list[str]]:
    if isinstance(value, dict):
        return {str(category): [str(skill) for skill in skills] for category, skills in value.items()}
    return {"general": [str(skill) for skill in value]}


def _register(identifier: str, value: object, index: dict[str, object]) -> None:
    if identifier in index:
        raise ValueError(f"Duplicate master CV id: {identifier}")
    index[identifier] = value


def _unique(values) -> list[str]:
    return list(dict.fromkeys(values))
