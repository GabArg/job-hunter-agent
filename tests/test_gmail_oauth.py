from __future__ import annotations

import base64
import json
import subprocess
import sys
from email import policy
from email.parser import BytesParser
from pathlib import Path

import pytest
from reportlab.pdfgen import canvas

from job_hunter.application import (DummyEmailProvider, EmailDraft, EmailDraftStatus,
    GmailEmailProvider, build_gmail_message, create_approved_gmail_draft)
from job_hunter.cli import main
from job_hunter.database import JobDatabase
from job_hunter.models import Job


class Execute:
    def __init__(self, result): self.result = result
    def execute(self): return self.result


class Drafts:
    def __init__(self): self.calls = []
    def create(self, **kwargs): self.calls.append(kwargs); return Execute({"id": "draft-123", "message": {"id": "msg-456"}})


class Users:
    def __init__(self): self.draft_api = Drafts()
    def drafts(self): return self.draft_api
    def getProfile(self, **kwargs): return Execute({"emailAddress": "connected@example.com"})


class Service:
    def __init__(self): self.user_api = Users()
    def users(self): return self.user_api


def valid_pdf(path: Path, text="Guido Arturo Broccoli CV") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    pdf = canvas.Canvas(str(path)); pdf.drawString(50, 800, text); pdf.save()
    return path


def decoded_message(raw: str):
    return BytesParser(policy=policy.default).parsebytes(base64.urlsafe_b64decode(raw.encode("ascii")))


def approved_flow(tmp_path):
    database = JobDatabase(tmp_path / "jobs.db")
    job = Job("Data Analyst", "Example", "Argentina", "remote", "Enviar CV a jobs@example.com", "test",
              "https://example.com/gmail", score=80, decision="APPLY", reasons={})
    database.upsert(job); job_id = database.list_jobs()[0]["id"]
    pdf = valid_pdf(tmp_path / "outputs" / str(job_id) / "cv.pdf")
    database.set_cv_pdf_result(job_id, pdf, "PDF_VALID", 1)
    database.save_email_draft(job_id, "jobs@example.com", "Approved subject", "Approved body")
    database.approve_email_draft(job_id)
    return database, job_id, pdf, EmailDraft("jobs@example.com", "Approved subject", "Approved body", [str(pdf)])


def test_missing_client_secret(tmp_path):
    provider = GmailEmailProvider(tmp_path / "gmail")
    assert provider.status()["configured"] is False
    with pytest.raises(RuntimeError, match="client_secret.json"): provider.authorize()


def test_oauth_paths_are_ignored():
    for path in ("private/gmail/client_secret.json", "private/gmail/token.json"):
        result = subprocess.run(["git", "check-ignore", path], capture_output=True, text=True)
        assert result.returncode == 0


def test_database_has_no_oauth_secrets(tmp_path):
    database = JobDatabase(tmp_path / "jobs.db")
    with database._connect() as connection:
        names = " ".join(row[1] for row in connection.execute("PRAGMA table_info(jobs)"))
        schema = " ".join(row[0] or "" for row in connection.execute("SELECT sql FROM sqlite_master"))
    assert all(value not in (names + schema).casefold() for value in ("access_token", "refresh_token", "client_secret"))


def test_mime_recipient_subject_body_attachment_and_base64(tmp_path):
    pdf = valid_pdf(tmp_path / "cv.pdf")
    raw = build_gmail_message("jobs@example.com", "Postulación", "Cuerpo aprobado", pdf)
    message = decoded_message(raw)
    assert message["To"] == "jobs@example.com" and message["Subject"] == "Postulación"
    assert message.get_body(preferencelist=("plain",)).get_content().strip() == "Cuerpo aprobado"
    attachment = next(message.iter_attachments())
    assert attachment.get_filename() == "Guido_Broccoli_CV.pdf"
    assert attachment.get_content_type() == "application/pdf" and attachment.get_payload(decode=True) == pdf.read_bytes()
    assert base64.urlsafe_b64encode(base64.urlsafe_b64decode(raw)).decode("ascii") == raw


def test_create_draft_uses_mock_gmail_api(tmp_path):
    pdf = valid_pdf(tmp_path / "cv.pdf"); service = Service()
    provider = GmailEmailProvider(tmp_path / "gmail", service=service); provider.account_email = "connected@example.com"
    draft_id = provider.create_draft(EmailDraft("jobs@example.com", "Subject", "Body", [str(pdf)]))
    call = service.user_api.draft_api.calls[0]
    assert draft_id == "draft-123" and provider.last_message_id == "msg-456"
    assert call["userId"] == "me" and decoded_message(call["body"]["message"]["raw"])["To"] == "jobs@example.com"


def test_draft_persisted_without_sent_or_applied(tmp_path):
    database, job_id, _, draft = approved_flow(tmp_path); provider = GmailEmailProvider(service=Service())
    provider.account_email = "connected@example.com"
    assert create_approved_gmail_draft(database, job_id, provider, draft) == "draft-123"
    row = database.get_job_row(job_id)
    assert row["gmail_draft_id"] == "draft-123" and row["gmail_message_id"] == "msg-456"
    assert row["email_draft_status"] == "GMAIL_DRAFT_CREATED"
    assert row["email_sent_at"] is None and row["application_status"] != "APPLIED"


def test_duplicate_gmail_draft_is_blocked(tmp_path):
    database, job_id, _, draft = approved_flow(tmp_path); provider = GmailEmailProvider(service=Service())
    provider.account_email = "connected@example.com"; create_approved_gmail_draft(database, job_id, provider, draft)
    with pytest.raises(ValueError, match="existente"): create_approved_gmail_draft(database, job_id, provider, draft)


def test_changed_email_marks_gmail_draft_stale(tmp_path):
    database, job_id, _, draft = approved_flow(tmp_path); provider = GmailEmailProvider(service=Service())
    provider.account_email = "connected@example.com"; create_approved_gmail_draft(database, job_id, provider, draft)
    database.save_email_draft(job_id, "new@example.com", "Changed", "Changed body")
    assert database.get_job_row(job_id)["email_draft_status"] == "GMAIL_DRAFT_STALE"


def test_changed_pdf_marks_gmail_draft_stale(tmp_path):
    database, job_id, pdf, draft = approved_flow(tmp_path); provider = GmailEmailProvider(service=Service())
    provider.account_email = "connected@example.com"; create_approved_gmail_draft(database, job_id, provider, draft)
    valid_pdf(pdf, "Updated CV"); database.set_cv_pdf_result(job_id, pdf, "PDF_VALID", 1)
    assert database.get_job_row(job_id)["email_draft_status"] == "GMAIL_DRAFT_STALE"


def test_invalid_pdf_rejected(tmp_path):
    bad = tmp_path / "cv.pdf"; bad.write_text("not pdf", encoding="utf-8")
    with pytest.raises(ValueError, match="valid readable PDF"): build_gmail_message("jobs@example.com", "S", "B", bad)


def test_real_gmail_send_is_blocked():
    with pytest.raises(NotImplementedError, match="disabled in Phase 5.1"):
        GmailEmailProvider(service=Service()).send(EmailDraft("a@b.com", "S", "B", []))


def test_oauth_cancellation_does_not_create_token(tmp_path):
    directory = tmp_path / "gmail"; directory.mkdir(); (directory / "client_secret.json").write_text("{}")
    class Flow:
        def run_local_server(self, **kwargs): raise RuntimeError("OAuth cancelled")
    provider = GmailEmailProvider(directory, flow_factory=lambda *args: Flow())
    with pytest.raises(RuntimeError, match="cancelled"): provider.authorize()
    assert not provider.token_path.exists()


def test_expired_token_refresh_is_reused(tmp_path):
    directory = tmp_path / "gmail"; directory.mkdir()
    (directory / "client_secret.json").write_text("{}"); (directory / "token.json").write_text("{}")
    class Credentials:
        expired = True; refresh_token = "local-refresh"; valid = False; refreshed = False
        def refresh(self, request): self.refreshed = True; self.expired = False; self.valid = True
        def to_json(self): return json.dumps({"token": "local-redacted"})
    credentials = Credentials(); service = Service()
    provider = GmailEmailProvider(directory, credentials_loader=lambda *args: credentials,
        request_factory=lambda: object(), service_builder=lambda *args, **kwargs: service,
        flow_factory=lambda *args: pytest.fail("OAuth flow should not run"))
    assert provider.authorize() == "connected@example.com" and credentials.refreshed


def test_gmail_failure_is_audited_without_secret(tmp_path):
    database, job_id, _, draft = approved_flow(tmp_path)
    class Failure(GmailEmailProvider):
        account_email = "connected@example.com"
        def __init__(self): self.service = object(); self.last_message_id = None
        def create_draft(self, draft): raise RuntimeError("access_token=super-secret network failed")
    with pytest.raises(RuntimeError): create_approved_gmail_draft(database, job_id, Failure(), draft)
    event = database.list_gmail_events()[0]
    assert event["action"] == "GMAIL_DRAFT_FAILED" and "super-secret" not in event["error"]


def test_gmail_status_without_credentials(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["job-hunter", "gmail-status", "--credentials-dir", str(tmp_path / "gmail"),
                                      "--database", str(tmp_path / "jobs.db")])
    main(); output = capsys.readouterr().out
    assert "Configured: no" in output and "Authorized: no" in output and "Token path: missing" in output


def test_backward_compatible_dummy_provider_and_states():
    provider = DummyEmailProvider(); draft = EmailDraft("a@b.com", "S", "B", [])
    assert provider.send(draft).startswith("dummy-sent-")
    assert EmailDraftStatus.GENERATED.value == "GENERATED" and EmailDraftStatus.SENT.value == "SENT"


def test_dashboard_has_no_real_send_action():
    source = Path("app/streamlit_app.py").read_text(encoding="utf-8")
    assert "Crear borrador en Gmail" in source and "Enviar email" not in source
