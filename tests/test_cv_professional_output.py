from __future__ import annotations

from email import policy
from email.parser import BytesParser
import base64
from pathlib import Path

from pypdf import PdfReader

from job_hunter.application import build_gmail_message
from job_hunter.cv import adapt_cv, load_master_cv, professional_cv_paths, professional_cv_stem, render_cv_pdf
from job_hunter.cv.filenames import MAX_CV_FILENAME_LENGTH, is_professional_cv_filename
from job_hunter.database import JobDatabase
from job_hunter.models import Job
from job_hunter.operations import generate_job_cv


MASTER = "private/master_cv.yaml"


def _job(title="Business Analyst – Data", company="Caramel", description=None, *, decision="APPLY"):
    description = description or (
        "Business Analysis, data projects, business requirements, stakeholders, SQL, Python, Power BI, "
        "Excel, reporting and KPI design."
    )
    return Job(title, company, "Argentina", "remote", description, "test",
               "https://example.com/professional-cv", score=85, decision=decision, reasons={})


def _cv(job=None):
    return adapt_cv(job or _job(), load_master_cv(MASTER))


def test_professional_filename_by_job_and_sanitization():
    cv = _cv()
    assert professional_cv_stem(cv) == "Guido_Broccoli_CV_Business_Analyst_Data_Caramel"
    unusual = _cv(_job("Data / BI: Analítica", "Compañía * Internacional"))
    stem = professional_cv_stem(unusual)
    assert stem == "Guido_Broccoli_CV_Data_BI_Analitica_Compania_Internacional"
    assert is_professional_cv_filename(stem + ".pdf")


def test_long_filename_is_windows_safe_and_bounded():
    cv = _cv(_job("Business Analyst Data " * 15, "Long Company Name " * 15))
    name = professional_cv_paths("outputs", cv)[0].name
    assert len(name) <= MAX_CV_FILENAME_LENGTH and is_professional_cv_filename(name)


def test_explicit_core_skills_win_over_secondary_tools():
    skills = _cv().skills
    for value in ("SQL", "Python", "Power BI"):
        assert value in skills
    assert max(skills.index(value) for value in ("SQL", "Python", "Power BI")) < min(
        (skills.index(value) for value in ("AWS", "Git", "Generative AI") if value in skills), default=len(skills)
    )


def test_business_data_courses_are_data_relevant_and_limited():
    courses = [course.program for course in _cv().courses]
    assert courses == ["Formación continua en datos", "Datos y tecnología"]
    assert len(courses) <= 2 and "AWS re/Start" not in courses and "Cybersecurity" not in courses


def test_summary_is_compact_factual_and_english_is_unchanged():
    cv = _cv()
    assert cv.professional_summary.count(".") == 3
    assert len(cv.professional_summary) < 500
    assert cv.professional_summary_source_fact_ids
    assert [(item.language, item.level) for item in cv.languages][-1] == (
        "Inglés", "Intermedio / lectura técnica"
    )


def test_project_links_are_only_factual_and_use_compact_labels(tmp_path):
    master = load_master_cv(MASTER)
    factual_links = {link for project in master.projects for link in project.links}
    cv = _cv()
    assert {link for project in cv.project_sections for link in project.links} <= factual_links
    pdf, html = professional_cv_paths(tmp_path, cv)
    result = render_cv_pdf(cv, pdf, html)
    source = result.html_path.read_text(encoding="utf-8")
    assert "github.com/GabArg" in source and ">GitHub<" in source
    assert "github.com/GabArg/NodoScouting" not in source


def test_caramel_pdf_is_valid_balanced_and_factual(tmp_path):
    cv = _cv(); pdf, html = professional_cv_paths(tmp_path, cv)
    result = render_cv_pdf(cv, pdf, html)
    text_by_page = [page.extract_text() or "" for page in PdfReader(str(pdf)).pages]
    assert result.validation_status == "PDF_VALID" and result.page_count <= 2
    assert result.page_balance_ratio >= 0.6
    assert not text_by_page[0].rstrip().endswith(("PROYECTOS DESTACADOS", "CURSOS Y CERTIFICACIONES"))
    assert all(identifier in load_master_cv(MASTER).fact_index for section in [*cv.experience_sections, *cv.project_sections]
               for bullet in section.bullets for identifier in bullet.source_fact_ids)


def test_database_stores_real_path_and_gmail_uses_real_filename(tmp_path):
    database = JobDatabase(tmp_path / "jobs.db"); database.upsert(_job())
    job_id = database.list_jobs()[0]["id"]
    generate_job_cv(database.path, job_id, MASTER, tmp_path / "outputs")
    row = database.get_job_row(job_id); pdf = Path(row["cv_pdf_path"])
    assert pdf.is_file() and pdf.name == "Guido_Broccoli_CV_Business_Analyst_Data_Caramel.pdf"
    raw = build_gmail_message("jobs@example.com", "Subject", "Body", pdf)
    message = BytesParser(policy=policy.default).parsebytes(base64.urlsafe_b64decode(raw))
    assert next(message.iter_attachments()).get_filename() == pdf.name
