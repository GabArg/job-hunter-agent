from __future__ import annotations

from pathlib import Path

import pytest

from job_hunter.application import DummyEmailProvider, EmailComposer, EmailDraft, EmailProvider, GmailEmailProvider, send_approved_email
from job_hunter.application.detector import detect_application_channel, detect_language, extract_recruiting_emails
from job_hunter.application.models import ApplicationMethod, JobLanguage
from job_hunter.cv import load_master_cv
from job_hunter.database import JobDatabase
from job_hunter.models import Job
from job_hunter.operations import generate_job_cv, prepare_application_email

MASTER = "private/master_cv.yaml"


def make_job(description="Enviar CV a talentos@example.com", url="https://company.example/jobs/1", decision="APPLY"):
    return Job("Business Analyst", "Example Company", "Argentina", "Remote", description, "test", url,
               score=80, decision=decision, reasons={"matched_skills": [], "missing_skills": [],
               "hard_reject_reasons": [], "positive_reasons": []})


@pytest.mark.parametrize(("text", "email"), [
    ("Enviar CV a rrhh@empresa.com", "rrhh@empresa.com"),
    ("Please send resume to jobs@company.com", "jobs@company.com"),
])
def test_detects_email_application(text, email):
    result = detect_application_channel(text, "")
    assert result.method == ApplicationMethod.EMAIL and result.email == email


@pytest.mark.parametrize("phrase", [
    "envía tu CV a", "envia tu CV a", "enviá tu CV a", "enviar CV a",
    "envíanos tu CV a", "envianos tu CV a", "mandá tu CV a", "manda tu CV a",
    "compartinos tu CV a", "compartí tu CV a", "postulate enviando tu CV a",
])
def test_spanish_email_application_variants(phrase):
    result = detect_application_channel(f"{phrase} rrhh@empresa.com", "")
    assert result.method == ApplicationMethod.EMAIL
    assert result.email == "rrhh@empresa.com"


def test_recruiting_context_detects_email_without_exact_command():
    result = detect_application_channel("Postulaciones: rrhh@empresa.com", "")
    assert result.method == ApplicationMethod.EMAIL and result.email == "rrhh@empresa.com"


@pytest.mark.parametrize("text", [
    "[amesen@infotreeservice.com](mailto:amesen@infotreeservice.com)",
    r"mailto\:amesen@infotreeservice.com",
])
def test_mailto_formats_extract_clean_email(text):
    assert extract_recruiting_emails(f"Enviar CV a {text}") == ["amesen@infotreeservice.com"]


def test_detects_link_link_email_and_unknown():
    assert detect_application_channel("Apply through our portal", "https://company.test/apply").method == ApplicationMethod.LINK
    both = detect_application_channel("Enviar CV a talentos@empresa.com o apply here", "https://company.test/apply")
    assert both.method == ApplicationMethod.LINK_EMAIL
    assert detect_application_channel("Información general", "").method == ApplicationMethod.UNKNOWN


def test_extracts_valid_email_and_ignores_non_email_or_support():
    assert extract_recruiting_emails("Contactar talentos@empresa.com") == ["talentos@empresa.com"]
    assert extract_recruiting_emails("No email here") == []
    assert extract_recruiting_emails("Soporte: support@empresa.com") == []
    assert detect_application_channel("Para consultas técnicas: soporte@empresa.com", "").method == ApplicationMethod.UNKNOWN


def test_internal_manual_url_is_not_a_link_channel():
    result = detect_application_channel("Enviar CV a rrhh@empresa.com", "manual://stable-fingerprint")
    assert result.method == ApplicationMethod.EMAIL and result.application_url is None


def test_multiple_emails_require_review_without_silent_selection():
    result = detect_application_channel("Enviar CV a rrhh@empresa.com o talentos@empresa.com", "")
    assert result.email is None and result.requires_review and len(result.email_candidates) == 2


def test_detects_salary_instruction_and_required_subject():
    result = detect_application_channel("Enviar CV con remuneración pretendida a rrhh@empresa.com. Asunto obligatorio: REF-BA-2026", "")
    assert "remuneración pretendida" in result.instructions
    assert result.required_subject == "REF-BA-2026"


def test_default_and_required_subject(tmp_path):
    cv = tmp_path / "cv.html"; cv.write_text("<html></html>", encoding="utf-8")
    master = load_master_cv(MASTER)
    default = EmailComposer().compose(make_job("Buscamos experiencia. Enviar CV a rrhh@empresa.com"), master, cv)
    required = EmailComposer().compose(make_job("Enviar CV a rrhh@empresa.com. Asunto: REF-123"), master, cv)
    assert default.subject == "Postulación — Business Analyst — Guido Broccoli"
    assert required.subject == "REF-123"


def test_spanish_and_english_email_body(tmp_path):
    cv = tmp_path / "cv.html"; cv.write_text("<html></html>", encoding="utf-8"); master = load_master_cv(MASTER)
    spanish = EmailComposer().compose(make_job("Buscamos experiencia para el puesto. Enviar CV a rrhh@empresa.com"), master, cv)
    english = EmailComposer().compose(make_job("We are hiring for this position. Requirements listed. Send resume to jobs@company.com"), master, cv)
    assert spanish.body.startswith("Hola,") and "gestión comercial y operativa" in spanish.body
    assert english.body.startswith("Hello,") and "business and operations" in english.body
    assert detect_language("We are hiring. Requirements for this position.") == JobLanguage.ENGLISH


def setup_email_flow(tmp_path, description="Buscamos experiencia. Enviar CV a talentos@example.com"):
    database = JobDatabase(tmp_path / "jobs.db"); database.upsert(make_job(description))
    job_id = database.list_jobs()[0]["id"]
    generate_job_cv(database.path, job_id, MASTER, tmp_path / "outputs")
    draft = prepare_application_email(database.path, job_id, MASTER, tmp_path / "outputs")
    return database, job_id, draft


def test_cannot_send_without_approved(tmp_path):
    database, job_id, draft = setup_email_flow(tmp_path)
    with pytest.raises(ValueError, match="APPROVED"): send_approved_email(database, job_id, DummyEmailProvider(), draft)


def test_dummy_provider_is_local_and_send_still_requires_manual_applied_tracking(tmp_path):
    database, job_id, draft = setup_email_flow(tmp_path); provider = DummyEmailProvider()
    database.approve_email_draft(job_id); message_id = send_approved_email(database, job_id, provider, draft)
    row = database.get_job_row(job_id)
    assert message_id.startswith("dummy-") and provider.sent_messages == [draft]
    assert row["email_draft_status"] == "SENT" and row["application_status"] != "APPLIED"
    assert row["email_sent_at"] and row["applied_at"] is None and row["application_channel_used"] == "EMAIL"


class FailingProvider(EmailProvider):
    def authorize(self): pass
    def create_draft(self, draft): raise RuntimeError("failed")
    def send(self, draft, message_id=None): raise RuntimeError("failed")


def test_send_failure_does_not_mark_applied(tmp_path):
    database, job_id, draft = setup_email_flow(tmp_path); database.approve_email_draft(job_id)
    with pytest.raises(RuntimeError): send_approved_email(database, job_id, FailingProvider(), draft)
    row = database.get_job_row(job_id)
    assert row["email_draft_status"] == "APPROVED" and row["application_status"] != "APPLIED"


def test_send_rejects_arbitrary_attachment(tmp_path):
    database, job_id, draft = setup_email_flow(tmp_path); database.approve_email_draft(job_id)
    arbitrary = tmp_path / "secret.txt"; arbitrary.write_text("not a CV", encoding="utf-8")
    unsafe = EmailDraft(draft.recipient, draft.subject, draft.body, [str(arbitrary)])
    with pytest.raises(ValueError, match="generated CV"): send_approved_email(database, job_id, DummyEmailProvider(), unsafe)
    assert database.get_job_row(job_id)["application_status"] != "APPLIED"


def test_opening_link_does_not_mark_applied(tmp_path):
    database = JobDatabase(tmp_path / "jobs.db"); database.upsert(make_job("Apply through portal"))
    row = database.list_jobs()[0]
    _ = row["application_url"]  # The dashboard link is read-only.
    assert database.get_job_row(row["id"])["application_status"] == "NEW"


def test_link_email_requires_selected_channel(tmp_path):
    database = JobDatabase(tmp_path / "jobs.db")
    database.upsert(make_job("Buscamos experiencia. Enviar CV a talentos@example.com o apply here"))
    job_id = database.list_jobs()[0]["id"]
    generate_job_cv(database.path, job_id, MASTER, tmp_path / "outputs")
    with pytest.raises(ValueError, match="Select EMAIL"): prepare_application_email(database.path, job_id, MASTER, tmp_path / "outputs")
    database.select_application_channel(job_id, "EMAIL")
    assert prepare_application_email(database.path, job_id, MASTER, tmp_path / "outputs").recipient == "talentos@example.com"


def test_email_edit_resets_to_generated_before_reapproval(tmp_path):
    database, job_id, draft = setup_email_flow(tmp_path); database.approve_email_draft(job_id)
    database.save_email_draft(job_id, draft.recipient, "Edited subject", "Edited body")
    row = database.get_job_row(job_id)
    assert row["email_draft_status"] == "GENERATED" and row["email_subject"] == "Edited subject"


def test_gmail_is_inactive_and_private_credentials_are_ignored(tmp_path):
    with pytest.raises(RuntimeError): GmailEmailProvider(tmp_path / "gmail-not-configured").authorize()
    ignore = Path(".gitignore").read_text(encoding="utf-8")
    assert "private/" in ignore


def test_no_credentials_are_versioned():
    tracked_text = "\n".join(path.read_text(encoding="utf-8", errors="ignore") for path in Path("config").glob("*.yaml"))
    assert "client_secret.json" not in tracked_text and "gmail_password" not in tracked_text
