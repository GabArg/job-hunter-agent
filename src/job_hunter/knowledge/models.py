from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import StrEnum
from typing import Any
from datetime import datetime, timezone


class ProposalType(StrEnum):
    COURSE = "COURSE"
    CERTIFICATION = "CERTIFICATION"
    PROJECT = "PROJECT"
    PROJECT_UPDATE = "PROJECT_UPDATE"
    SKILL = "SKILL"
    EXPERIENCE = "EXPERIENCE"
    EXPERIENCE_UPDATE = "EXPERIENCE_UPDATE"
    EDUCATION = "EDUCATION"
    LANGUAGE = "LANGUAGE"
    ACHIEVEMENT = "ACHIEVEMENT"


class ProposalStatus(StrEnum):
    DRAFT = "DRAFT"
    VALIDATED = "VALIDATED"
    PENDING_APPROVAL = "PENDING_APPROVAL"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    APPLIED = "APPLIED"


@dataclass(slots=True)
class UpdateProposal:
    id: str
    type: ProposalType
    status: ProposalStatus
    created_at: str
    updated_at: str
    title: str
    source: str
    evidence: list[str]
    proposed_changes: dict[str, Any]
    notes: str = ""
    confidence: float = 1.0
    validation_errors: list[str] = field(default_factory=list)

    def touch(self) -> None:
        self.updated_at = datetime.now(timezone.utc).isoformat(timespec="seconds")

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["type"], value["status"] = self.type.value, self.status.value
        return value

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "UpdateProposal":
        data = dict(value)
        data["type"], data["status"] = ProposalType(data["type"]), ProposalStatus(data["status"])
        return cls(**data)
