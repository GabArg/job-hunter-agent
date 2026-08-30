from __future__ import annotations

from pathlib import Path

from ..cv.models import MasterCV
from ..models import Job
from .detector import detect_application_channel
from .models import EmailDraft, JobLanguage


class EmailComposer:
    def compose(self, job: Job, master: MasterCV, cv_path: str | Path, allow_html_development: bool = True) -> EmailDraft:
        detection = detect_application_channel(job.description, job.url)
        if not detection.email: raise ValueError("A single reviewed application email is required")
        attachment = Path(cv_path)
        if not attachment.is_file(): raise FileNotFoundError("Generate the tailored CV before preparing email")
        if attachment.suffix.lower() not in {".pdf", ".html"}: raise ValueError("Only generated PDF or development HTML CV attachments are allowed")
        pending_pdf = attachment.suffix.lower() == ".html"
        if pending_pdf and not allow_html_development: raise ValueError("PDF CV is required outside development mode")
        name = master.personal.get("name", "Guido Broccoli")
        linkedin, github = master.personal.get("linkedin", ""), master.personal.get("github", "")
        subject = detection.required_subject or f"Postulación — {job.title} — Guido Broccoli"
        if detection.language == JobLanguage.ENGLISH:
            body = (f"Hello,\n\nI am writing to apply for the {job.title} role at {job.company}.\n\n"
                    "My background combines business and operations experience with hands-on work in data analytics, reporting and process improvement.\n\n"
                    f"I have attached my CV for your consideration.\n\nBest regards,\n{name}")
        else:
            body = (f"Hola,\n\nMe contacto para postularme a la posición de {job.title} en {job.company}.\n\n"
                    "Mi trayectoria combina gestión comercial y operativa con una orientación profesional actual hacia Data Analytics y Business Analytics. "
                    "Cuento con experiencia en KPIs, reporting y análisis para apoyar decisiones de negocio.\n\n"
                    f"Adjunto mi CV adaptado a la posición. Quedo a disposición para ampliar cualquier información.\n\nSaludos,\n{name}")
        links = "\n".join(value for value in (f"LinkedIn: {linkedin}" if linkedin else "", f"GitHub: {github}" if github else "") if value)
        if links: body += f"\n{links}"
        return EmailDraft(detection.email, subject, body, [str(attachment)], pending_pdf)
