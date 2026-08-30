from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING
from uuid import uuid4

from .models import EmailDraft

if TYPE_CHECKING:
    from ..database import JobDatabase


class EmailProvider(ABC):
    @abstractmethod
    def authorize(self) -> None: ...
    @abstractmethod
    def create_draft(self, draft: EmailDraft) -> str: ...
    @abstractmethod
    def send(self, draft: EmailDraft, message_id: str | None = None) -> str: ...


@dataclass
class DummyEmailProvider(EmailProvider):
    drafts: list[EmailDraft] = field(default_factory=list); sent_messages: list[EmailDraft] = field(default_factory=list)
    def authorize(self) -> None: return None
    def create_draft(self, draft: EmailDraft) -> str: self.drafts.append(draft); return f"dummy-draft-{uuid4().hex[:10]}"
    def send(self, draft: EmailDraft, message_id: str | None = None) -> str:
        self.sent_messages.append(draft); return message_id or f"dummy-sent-{uuid4().hex[:10]}"


class GmailEmailProvider(EmailProvider):
    """OAuth boundary for future Gmail integration; intentionally inactive by default."""
    def __init__(self, credentials_dir: str | Path = "private/gmail"):
        self.credentials_dir = Path(credentials_dir)
    def authorize(self) -> None: raise RuntimeError("Gmail OAuth is not configured; provide private/gmail credentials explicitly")
    def create_draft(self, draft: EmailDraft) -> str: raise RuntimeError("Gmail provider is not activated")
    def send(self, draft: EmailDraft, message_id: str | None = None) -> str: raise RuntimeError("Gmail provider is not activated")


def send_approved_email(database: "JobDatabase", job_id: int, provider: EmailProvider, draft: EmailDraft) -> str:
    row = database.get_job_row(job_id)
    if row is None: raise KeyError(f"Job not found: {job_id}")
    if row["email_draft_status"] != "APPROVED": raise ValueError("Email must be APPROVED before SEND")
    if row.get("cv_pdf_status") != "PDF_VALID": raise ValueError("A VALID PDF CV is required before SEND")
    if row["application_method"] == "LINK_EMAIL" and row["selected_application_channel"] != "EMAIL":
        raise ValueError("Select EMAIL as application channel before sending")
    if draft.recipient != row["application_email"] or draft.subject != row["email_subject"] or draft.body != row["email_body"]:
        raise ValueError("SEND payload must match the approved stored draft")
    if len(draft.attachments) != 1:
        raise ValueError("Exactly one generated CV attachment is required")
    attachment = Path(draft.attachments[0]).resolve()
    if not attachment.is_file() or attachment.name != "cv.pdf" or attachment.parent.name != str(job_id):
        raise ValueError("Attachment must be the generated CV for this job")
    message_id = provider.send(draft, row.get("email_message_id"))
    database.mark_email_sent(job_id, message_id, "EMAIL")
    return message_id
