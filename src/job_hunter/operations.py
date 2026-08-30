from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from .cv import adapt_cv, load_master_cv, professional_cv_paths, render_cv_pdf
from .database import JobDatabase
from .application import EmailComposer, EmailDraft


def generate_job_cv(database_path: str | Path, job_id: int, master_path: str | Path = "private/master_cv.yaml",
                    output_root: str | Path = "outputs/cvs", allow_reject: bool = False) -> tuple[Path, object]:
    database = JobDatabase(database_path); job = database.get_job(job_id=job_id)
    if job is None: raise KeyError(f"Job not found: {job_id}")
    adapted = adapt_cv(job, load_master_cv(master_path), allow_reject=allow_reject)
    base = Path(output_root) / str(job_id)
    pdf_path, html_path = professional_cv_paths(base, adapted)
    rendered = render_cv_pdf(adapted, pdf_path, html_path)
    database.set_cv_pdf_result(job_id, rendered.pdf_path, rendered.validation_status, rendered.page_count)
    if rendered.validation_status != "PDF_VALID":
        raise ValueError("PDF CV validation failed: " + "; ".join(rendered.warnings))
    database.set_application_status(job_id, "CV_GENERATED")
    return rendered.html_path, adapted


def prepare_application_email(database_path: str | Path, job_id: int, master_path: str | Path = "private/master_cv.yaml",
                              output_root: str | Path = "outputs/cvs") -> EmailDraft:
    database = JobDatabase(database_path); row = database.get_job_row(job_id); job = database.get_job(job_id=job_id)
    if row is None or job is None: raise KeyError(f"Job not found: {job_id}")
    if row["application_method"] not in {"EMAIL", "LINK_EMAIL"}: raise ValueError("This job has no reviewed email application channel")
    if row["application_method"] == "LINK_EMAIL" and row["selected_application_channel"] != "EMAIL":
        raise ValueError("Select EMAIL before preparing the draft")
    cv_path = Path(row.get("cv_pdf_path") or "")
    if row.get("cv_pdf_status") != "PDF_VALID" or not cv_path.is_file():
        raise ValueError("Generate and validate the PDF CV before preparing an email")
    draft = EmailComposer().compose(job, load_master_cv(master_path), cv_path, allow_html_development=False)
    database.save_email_draft(job_id, draft.recipient, draft.subject, draft.body)
    return draft


def next_schedule_time(times: list[str], now: datetime | None = None) -> datetime | None:
    if not times: return None
    current = now or datetime.now().astimezone()
    candidates = []
    for offset in (0, 1):
        day = (current + timedelta(days=offset)).date()
        for value in times:
            hour, minute = (int(part) for part in value.split(":"))
            candidate = datetime.combine(day, datetime.min.time(), tzinfo=current.tzinfo).replace(hour=hour, minute=minute)
            if candidate > current: candidates.append(candidate)
    return min(candidates) if candidates else None
