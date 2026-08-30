from __future__ import annotations

from abc import ABC, abstractmethod
import base64
import re
from dataclasses import dataclass, field
from email.message import EmailMessage
from email.utils import parseaddr
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
    """Gmail OAuth Desktop provider limited to composing drafts."""
    SCOPES = ["https://www.googleapis.com/auth/gmail.compose"]

    def __init__(self, credentials_dir: str | Path = "private/gmail", *, service=None,
                 credentials_loader=None, flow_factory=None, request_factory=None, service_builder=None):
        self.credentials_dir = Path(credentials_dir)
        self.client_secret_path = self.credentials_dir / "client_secret.json"
        self.token_path = self.credentials_dir / "token.json"
        self.service = service
        self.credentials = None
        self.account_email: str | None = None
        self.last_message_id: str | None = None
        self._credentials_loader = credentials_loader
        self._flow_factory = flow_factory
        self._request_factory = request_factory
        self._service_builder = service_builder

    @property
    def configured(self) -> bool: return self.client_secret_path.is_file()
    @property
    def authorized(self) -> bool:
        if not self.token_path.is_file(): return False
        try:
            from google.oauth2.credentials import Credentials
            credentials = Credentials.from_authorized_user_file(str(self.token_path), self.SCOPES)
            return bool(credentials.valid or credentials.refresh_token)
        except Exception:
            return False

    def status(self) -> dict[str, object]:
        return {"configured": self.configured, "authorized": self.authorized,
                "account": self.account_email, "token_path": "configured" if self.authorized else "missing"}

    def authorize(self) -> str:
        if not self.configured:
            raise RuntimeError("Gmail todavía no está conectado. Falta private/gmail/client_secret.json")
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials
        from google_auth_oauthlib.flow import InstalledAppFlow
        from googleapiclient.discovery import build

        loader = self._credentials_loader or Credentials.from_authorized_user_file
        flow_factory = self._flow_factory or InstalledAppFlow.from_client_secrets_file
        request_factory = self._request_factory or Request
        builder = self._service_builder or build
        credentials = None
        if self.token_path.is_file():
            try: credentials = loader(str(self.token_path), self.SCOPES)
            except Exception: credentials = None
        if credentials and credentials.expired and credentials.refresh_token:
            credentials.refresh(request_factory())
        elif not credentials or not credentials.valid:
            flow = flow_factory(str(self.client_secret_path), self.SCOPES)
            credentials = flow.run_local_server(port=0)
        self.credentials_dir.mkdir(parents=True, exist_ok=True)
        self.token_path.write_text(credentials.to_json(), encoding="utf-8")
        self.credentials = credentials
        self.service = builder("gmail", "v1", credentials=credentials, cache_discovery=False)
        profile = self.service.users().getProfile(userId="me").execute()
        self.account_email = str(profile.get("emailAddress") or "")
        if not self.account_email: raise RuntimeError("Gmail no devolvió la cuenta autenticada")
        return self.account_email

    def create_draft(self, draft: EmailDraft) -> str:
        if self.service is None: raise RuntimeError("Gmail todavía no está autorizado")
        if len(draft.attachments) != 1: raise ValueError("Exactly one PDF attachment is required")
        raw = build_gmail_message(draft.recipient, draft.subject, draft.body, draft.attachments[0])
        response = self.service.users().drafts().create(userId="me", body={"message": {"raw": raw}}).execute()
        draft_id = str(response.get("id") or "")
        if not draft_id: raise RuntimeError("Gmail API no devolvió draft ID")
        message = response.get("message") or {}; self.last_message_id = str(message.get("id") or "") or None
        return draft_id

    def send(self, draft: EmailDraft, message_id: str | None = None) -> str:
        raise NotImplementedError("Real Gmail sending is disabled in Phase 5.1")


def build_gmail_message(recipient: str, subject: str, body: str, pdf_path: str | Path) -> str:
    address = parseaddr(recipient)[1]
    if not address or address != recipient or "@" not in address: raise ValueError("Invalid recipient")
    attachment = Path(pdf_path)
    if not attachment.is_file() or attachment.name != "cv.pdf" or attachment.suffix.lower() != ".pdf":
        raise ValueError("A generated cv.pdf attachment is required")
    try:
        from pypdf import PdfReader
        reader = PdfReader(str(attachment))
        extracted = "".join(page.extract_text() or "" for page in reader.pages)
        if not reader.pages or len(reader.pages) > 2 or not extracted.strip():
            raise ValueError("PDF must contain selectable text in at most two pages")
    except ValueError:
        raise
    except Exception as exc:
        raise ValueError("Attachment is not a valid readable PDF") from exc
    message = EmailMessage()
    message["To"] = recipient; message["Subject"] = subject
    message.set_content(body, subtype="plain", charset="utf-8")
    message.add_attachment(attachment.read_bytes(), maintype="application", subtype="pdf",
                           filename="Guido_Broccoli_CV.pdf")
    return base64.urlsafe_b64encode(message.as_bytes()).decode("ascii")


def create_approved_gmail_draft(database: "JobDatabase", job_id: int,
                                provider: GmailEmailProvider, draft: EmailDraft) -> str:
    row = database.get_job_row(job_id)
    if row is None: raise KeyError(f"Job not found: {job_id}")
    if row["email_draft_status"] == "GMAIL_DRAFT_CREATED" or row.get("gmail_draft_id"):
        raise ValueError("Borrador Gmail existente; no se creará un duplicado")
    if row["email_draft_status"] != "APPROVED": raise ValueError("Email must be APPROVED before creating a Gmail draft")
    if row.get("cv_pdf_status") != "PDF_VALID": raise ValueError("A VALID PDF CV is required")
    if draft.recipient != row["application_email"] or draft.subject != row["email_subject"] or draft.body != row["email_body"]:
        raise ValueError("Gmail draft payload must match the approved stored draft")
    attachment = Path(draft.attachments[0]).resolve() if len(draft.attachments) == 1 else Path()
    expected = Path(row["cv_pdf_path"] or "").resolve()
    if not attachment.is_file() or attachment != expected or attachment.name != "cv.pdf" or attachment.parent.name != str(job_id):
        raise ValueError("Attachment must be the VALID PDF generated for this job")
    try:
        if provider.service is None:
            account = provider.authorize()
            database.record_gmail_event("GMAIL_AUTHORIZED", "SUCCESS", account_email=account)
        draft_id = provider.create_draft(draft)
        database.save_gmail_draft(job_id, draft_id, provider.last_message_id, provider.account_email or "")
        database.record_gmail_event("GMAIL_DRAFT_CREATED", "SUCCESS", job_id=job_id,
            recipient=draft.recipient, draft_id=draft_id, account_email=provider.account_email)
        return draft_id
    except Exception as exc:
        database.record_gmail_event("GMAIL_DRAFT_FAILED", "FAILED", job_id=job_id,
            recipient=draft.recipient, account_email=provider.account_email, error=str(exc))
        raise


def sanitize_gmail_error(value: object) -> str:
    text = str(value)[:1_000]
    text = re.sub(r"(?i)(access[_ -]?token|refresh[_ -]?token|client[_ -]?secret|authorization)"
                  r"\s*[:=]\s*[^\s,;]+", r"\1=[REDACTED]", text)
    text = re.sub(r"(?i)bearer\s+[A-Za-z0-9._~+/-]+=*", "Bearer [REDACTED]", text)
    return text[:500]


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
