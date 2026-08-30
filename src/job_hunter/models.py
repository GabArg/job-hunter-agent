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
    published_at: str | None = None
    discovered_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(timespec="seconds")
    )
    id: int | None = None
    required_years: float | None = None
    required_english: str | None = None
    seniority: str | None = None
    detected_skills: list[str] = field(default_factory=list)
    job_requirements: list[str] = field(default_factory=list)
    role_subtype: str | None = None
    application_method: str = "UNKNOWN"
    application_email: str | None = None
    application_url: str | None = None
    application_instructions: list[str] = field(default_factory=list)
    email_subject: str | None = None
    email_body: str | None = None
    email_draft_status: str = "NOT_GENERATED"
    email_sent_at: str | None = None
    email_message_id: str | None = None
    selected_application_channel: str | None = None
    application_channel_used: str | None = None
    raw_data: dict[str, Any] | None = field(default=None, repr=False)
    sector: str = "Other"
    sector_confidence: float = 0.0
    priority_fresh: bool = False
    score: float | None = None
    decision: str | None = None
    reasons: dict[str, Any] = field(default_factory=dict)
    created_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(timespec="seconds")
    )


@dataclass(frozen=True, slots=True)
class Profile:
    search_queries: list[str]
    query_groups: dict[str, list[str]]
    career_targets: list[dict[str, Any]]
    target_roles: list[str]
    preferred_locations: list[str]
    preferred_work_modes: list[str]
    max_required_years: float
    allowed_seniority: list[str]
    english_level: str
    skills: list[str]
    hard_reject_rules: dict[str, bool]
    scoring_weights: dict[str, float]
    discovery_schedule: dict[str, Any] = field(default_factory=dict)
    discovery_targets: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    active_targets: list[dict[str, Any]] = field(default_factory=list)
    candidate_targets: list[dict[str, Any]] = field(default_factory=list)
    career_pages: list[dict[str, Any]] = field(default_factory=list)
    preferred_companies: list[str] = field(default_factory=list)
    priority_fresh_days: int = 3


@dataclass(frozen=True, slots=True)
class ScoreResult:
    score: float
    decision: str
    matched_skills: list[str]
    missing_skills: list[str]
    hard_reject_reasons: list[str]
    positive_reasons: list[str]
    job_requirements: list[str] = field(default_factory=list)
    matched_requirements: list[str] = field(default_factory=list)
    candidate_skills: list[str] = field(default_factory=list)
    target_profile_terms: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, object]:
        return {
            "score": self.score,
            "decision": self.decision,
            "matched_skills": self.matched_skills,
            "missing_skills": self.missing_skills,
            "hard_reject_reasons": self.hard_reject_reasons,
            "positive_reasons": self.positive_reasons,
            "job_requirements": self.job_requirements,
            "matched_requirements": self.matched_requirements,
            "candidate_skills": self.candidate_skills,
            "target_profile_terms": self.target_profile_terms,
        }
