from __future__ import annotations

import sys
from pathlib import Path

import pytest
from pypdf import PdfReader
from reportlab.pdfgen import canvas

from job_hunter.cli import main
from job_hunter.config import load_profile
from job_hunter.cv import adapt_cv, load_master_cv, render_cv_pdf, validate_pdf
from job_hunter.cv.pdf_renderer import PDF_INVALID, PDF_VALID, TOO_LONG
from job_hunter.cv.renderer import dynamic_professional_title
from job_hunter.cv.renderer import HTMLCVRenderer
from job_hunter.database import JobDatabase
from job_hunter.models import Job
from job_hunter.operations import generate_job_cv


MASTER = "private/master_cv.yaml"


def adapted(title="Business & Data Analyst"):
    profile = load_profile("config/profile.example.yaml")
    job = Job(title, "Example", "Buenos Aires", "hybrid",
              "SQL Power BI Excel KPIs reporting processes stakeholders", "test", "https://example.com/job",
              score=68, decision="REVIEW", reasons={})
    from job_hunter.normalizer import normalize_job
    from job_hunter.scorer import score_job
    normalize_job(job, profile.skills); scored = score_job(job, profile)
    job.score, job.decision, job.reasons = scored.score, "REVIEW", scored.as_dict()
    return adapt_cv(job, load_master_cv(MASTER))


@pytest.fixture(scope="module")
def rendered(tmp_path_factory):
    root = tmp_path_factory.mktemp("pdf")
    result = render_cv_pdf(adapted(), root / "cv.pdf", root / "cv.html")
    return result, adapted()


def extracted(result):
    return "\n".join(page.extract_text() or "" for page in PdfReader(str(result.pdf_path)).pages)


def test_render_pdf_valid(rendered): assert rendered[0].validation_status == PDF_VALID
def test_pdf_exists(rendered): assert rendered[0].pdf_path.is_file()
def test_pdf_text_selectable(rendered): assert len(extracted(rendered[0])) > 200
def test_pdf_contains_name(rendered): assert "Guido Arturo Broccoli" in extracted(rendered[0])
def test_pdf_contains_experience(rendered): assert "Esquinas Adrogué" in extracted(rendered[0])
def test_pdf_has_at_most_two_pages(rendered): assert rendered[0].page_count <= 2
def test_html_is_preserved(rendered): assert rendered[0].html_path.is_file() and "<!doctype html>" in rendered[0].html_path.read_text(encoding="utf-8")
def test_pdf_output_path(rendered): assert rendered[0].pdf_path.name == "cv.pdf"


def test_pdf_contains_no_invented_fact(rendered):
    assert "Invented Corporation" not in extracted(rendered[0])


def test_dynamic_title_does_not_invent_seniority():
    value = dynamic_professional_title(adapted("Senior Data Analyst"))
    assert value == "Data Analyst" and "Senior" not in value
    assert dynamic_professional_title(adapted("Ssr Business Analyst")) == "Business Analyst"


def test_links_are_preserved_as_annotations(rendered):
    reader = PdfReader(str(rendered[0].pdf_path))
    annotations = [annotation for page in reader.pages for annotation in (page.get("/Annots") or [])]
    assert annotations


class PageBackend:
    def __init__(self, cv, counts): self.cv, self.counts, self.calls = cv, list(counts), 0
    def __call__(self, html_path, pdf_path):
        count = self.counts[min(self.calls, len(self.counts) - 1)]; self.calls += 1
        pdf = canvas.Canvas(str(pdf_path))
        contacts = " ".join(self.cv.personal.get(key, "") for key in ("linkedin", "github", "email"))
        company = self.cv.experience_sections[0].company
        for _ in range(count):
            pdf.drawString(30, 800, self.cv.personal["name"]); pdf.drawString(30, 780, company)
            pdf.drawString(30, 760, contacts); pdf.showPage()
        pdf.save()


def test_page_compression_retries_and_succeeds(tmp_path):
    cv = adapted(); backend = PageBackend(cv, [3, 2])
    result = render_cv_pdf(cv, tmp_path / "cv.pdf", backend=backend)
    assert result.validation_status == PDF_VALID and result.page_count == 2 and backend.calls == 2
    assert "nivel 1" in result.warnings[0]


def test_too_long_after_safe_compression(tmp_path):
    cv = adapted(); result = render_cv_pdf(cv, tmp_path / "cv.pdf", backend=PageBackend(cv, [3]))
    assert result.validation_status == TOO_LONG and result.page_count == 3


def test_database_pdf_tracking(tmp_path):
    database = JobDatabase(tmp_path / "jobs.db")
    job = Job("Data Analyst", "Example", "Argentina", "remote", "SQL Power BI", "test",
              "https://example.com/tracking", score=80, decision="APPLY", reasons={})
    database.upsert(job); job_id = database.list_jobs()[0]["id"]
    generate_job_cv(database.path, job_id, MASTER, tmp_path / "outputs")
    row = database.get_job_row(job_id)
    assert row["cv_pdf_status"] == PDF_VALID and row["cv_pdf_pages"] <= 2 and Path(row["cv_pdf_path"]).is_file()


def test_email_approval_rejects_invalid_pdf(tmp_path):
    database = JobDatabase(tmp_path / "jobs.db")
    job = Job("Data Analyst", "Example", "Argentina", "remote", "Enviar CV a jobs@example.com", "test",
              "https://example.com/email", score=80, decision="APPLY", reasons={})
    database.upsert(job); job_id = database.list_jobs()[0]["id"]
    database.save_email_draft(job_id, "jobs@example.com", "Subject", "Body")
    database.set_cv_pdf_result(job_id, tmp_path / "bad.pdf", PDF_INVALID, 0)
    with pytest.raises(ValueError, match="VALID PDF"): database.approve_email_draft(job_id)


def test_validate_missing_pdf_is_invalid(tmp_path):
    result = validate_pdf(tmp_path / "missing.pdf", adapted())
    assert result.validation_status == PDF_INVALID


def test_cli_generate_cv(tmp_path, monkeypatch, capsys):
    database = JobDatabase(tmp_path / "jobs.db")
    database.upsert(Job("Business Analyst", "Example", "Argentina", "hybrid", "KPIs reporting", "test",
                        "https://example.com/cli", score=65, decision="REVIEW", reasons={}))
    job_id = database.list_jobs()[0]["id"]
    monkeypatch.setattr(sys, "argv", ["job-hunter", "generate-cv", str(job_id), "--database", str(database.path),
                                      "--master-cv", MASTER, "--output", str(tmp_path / "outputs")])
    main(); output = capsys.readouterr().out
    generated = list((tmp_path / "outputs" / str(job_id)).glob("Guido_Broccoli_CV_*.pdf"))
    assert "PDF: PDF_VALID" in output and len(generated) == 1


def test_dashboard_exposes_pdf_status_and_download():
    source = Path("app/streamlit_app.py").read_text(encoding="utf-8")
    assert "cv_pdf_status" in source and "Descargar PDF" in source


def test_windows_safe_nested_output(tmp_path):
    result = render_cv_pdf(adapted(), tmp_path / "folder with spaces" / "cv.pdf")
    assert result.validation_status == PDF_VALID and result.pdf_path.is_file()


def test_legacy_html_renderer_remains_available():
    assert "<html" in HTMLCVRenderer().render(adapted())
