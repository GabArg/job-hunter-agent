from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class ApplicationMethod(StrEnum): LINK = "LINK"; EMAIL = "EMAIL"; LINK_EMAIL = "LINK_EMAIL"; UNKNOWN = "UNKNOWN"
class EmailDraftStatus(StrEnum): NOT_GENERATED = "NOT_GENERATED"; GENERATED = "GENERATED"; APPROVED = "APPROVED"; SENT = "SENT"
class JobLanguage(StrEnum): SPANISH = "SPANISH"; ENGLISH = "ENGLISH"; UNKNOWN = "UNKNOWN"


@dataclass(frozen=True, slots=True)
class ApplicationDetection:
    method: ApplicationMethod
    email: str | None
    application_url: str | None
    instructions: list[str] = field(default_factory=list)
    email_candidates: list[str] = field(default_factory=list)
    requires_review: bool = False
    required_subject: str | None = None
    language: JobLanguage = JobLanguage.UNKNOWN


@dataclass(frozen=True, slots=True)
class EmailDraft:
    recipient: str
    subject: str
    body: str
    attachments: list[str]
    attachment_pending_pdf: bool = False
