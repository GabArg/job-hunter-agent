from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from .models import Profile

REQUIRED_KEYS = {
    "search_queries",
    "target_roles",
    "preferred_locations",
    "preferred_work_modes",
    "max_required_years",
    "allowed_seniority",
    "english_level",
    "skills",
    "hard_reject_rules",
    "scoring_weights",
}


def load_profile(path: str | Path) -> Profile:
    profile_path = Path(path)
    if not profile_path.is_file():
        raise FileNotFoundError(f"Profile not found: {profile_path}")
    with profile_path.open(encoding="utf-8") as handle:
        data: dict[str, Any] = yaml.safe_load(handle) or {}
    missing = REQUIRED_KEYS - data.keys()
    if missing:
        raise ValueError(f"Profile is missing keys: {', '.join(sorted(missing))}")
    weights = {str(k): float(v) for k, v in data["scoring_weights"].items()}
    if sum(weights.values()) <= 0:
        raise ValueError("scoring_weights must have a positive total")
    return Profile(
        search_queries=_normalized_list(data["search_queries"]),
        query_groups={
            str(name).strip().lower(): _normalized_list(values)
            for name, values in (data.get("query_groups") or {}).items()
        },
        career_targets=[dict(target) for target in (data.get("career_targets") or [])],
        target_roles=_normalized_list(data["target_roles"]),
        preferred_locations=_normalized_list(data["preferred_locations"]),
        preferred_work_modes=_normalized_list(data["preferred_work_modes"]),
        max_required_years=float(data["max_required_years"]),
        allowed_seniority=_normalized_list(data["allowed_seniority"]),
        english_level=str(data["english_level"]).strip().lower(),
        skills=_normalized_list(data["skills"]),
        hard_reject_rules={str(k): bool(v) for k, v in data["hard_reject_rules"].items()},
        scoring_weights=weights,
    )


def _normalized_list(values: list[object]) -> list[str]:
    return [str(value).strip().lower() for value in values]
