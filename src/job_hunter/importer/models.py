from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class ImportStatus(StrEnum):
    IMPORTED = "IMPORTED"
    DUPLICATE = "DUPLICATE"
    NEEDS_MANUAL_INPUT = "NEEDS_MANUAL_INPUT"
    UNSUPPORTED = "UNSUPPORTED"
    FAILED = "FAILED"


@dataclass(slots=True)
class ExtractedJob:
    title: str = ""
    company: str = ""
    location: str = ""
    work_mode: str = "unknown"
    description: str = ""
    published_at: str | None = None
    url: str = ""


@dataclass(slots=True)
class ImportResult:
    status: ImportStatus
    source_type: str
    canonical_url: str
    title: str = ""
    company: str = ""
    location: str = ""
    work_mode: str = "unknown"
    description: str = ""
    published_at: str | None = None
    application_method: str = "UNKNOWN"
    duplicate_job_id: int | None = None
    job_id: int | None = None
    warnings: list[str] = field(default_factory=list)
    extraction_method: str = ""
    decision: str | None = None
    score: float | None = None
    sector: str = "Other"
    reasons: dict = field(default_factory=dict)
