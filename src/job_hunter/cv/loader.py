from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from .models import MasterCV, SourceFact

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
    facts: dict[str, SourceFact] = {}
    summary = _facts(data["summary_facts"], "summary", None, facts)
    experience = []
    for index, entry in enumerate(data["experience"], 1):
        copied = dict(entry)
        copied["fact_objects"] = _facts(entry.get("facts", []), f"exp_{index:02d}_fact", index - 1, facts)
        copied["achievement_objects"] = _facts(
            entry.get("achievements", []), f"exp_{index:02d}_achievement", index - 1, facts
        )
        experience.append(copied)
    projects = []
    for index, entry in enumerate(data["projects"], 1):
        copied = dict(entry)
        copied["fact_objects"] = _facts(entry.get("facts", []), f"project_{index:02d}_fact", index - 1, facts)
        copied["metric_objects"] = _facts(entry.get("metrics", []), f"project_{index:02d}_metric", index - 1, facts)
        projects.append(copied)
    return MasterCV(
        personal={str(k): str(v) for k, v in data["personal"].items()},
        summary_facts=summary,
        experience=experience,
        projects=projects,
        education=[dict(item) for item in data["education"]],
        courses=[str(item) for item in data.get("courses", [])],
        skills=[str(item) for item in data["skills"]],
        languages=[dict(item) for item in data["languages"]],
        fact_index=facts,
    )


def _facts(values, prefix: str, owner: int | None, index: dict[str, SourceFact]) -> list[SourceFact]:
    results = []
    for number, value in enumerate(values, 1):
        fact_id = f"{prefix}_{number:02d}"
        fact = SourceFact(fact_id, str(value).strip(), prefix, owner)
        index[fact_id] = fact
        results.append(fact)
    return results
