from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


@dataclass(slots=True)
class Job:
    title: str
    company: str
    location: str
    work_mode: str
    description: str
    source: str
    url: str
    id: int | None = None
    required_years: float | None = None
    required_english: str | None = None
    seniority: str | None = None
    detected_skills: list[str] = field(default_factory=list)
    score: float | None = None
    decision: str | None = None
    reasons: dict[str, Any] = field(default_factory=dict)
    created_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(timespec="seconds")
    )


@dataclass(frozen=True, slots=True)
class Profile:
    target_roles: list[str]
    preferred_locations: list[str]
    preferred_work_modes: list[str]
    max_required_years: float
    allowed_seniority: list[str]
    english_level: str
    skills: list[str]
    hard_reject_rules: dict[str, bool]
    scoring_weights: dict[str, float]


@dataclass(frozen=True, slots=True)
class ScoreResult:
    score: float
    decision: str
    matched_skills: list[str]
    missing_skills: list[str]
    hard_reject_reasons: list[str]
    positive_reasons: list[str]

    def as_dict(self) -> dict[str, object]:
        return {
            "score": self.score,
            "decision": self.decision,
            "matched_skills": self.matched_skills,
            "missing_skills": self.missing_skills,
            "hard_reject_reasons": self.hard_reject_reasons,
            "positive_reasons": self.positive_reasons,
        }
