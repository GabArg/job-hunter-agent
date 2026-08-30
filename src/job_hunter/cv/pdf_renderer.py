from __future__ import annotations

import copy
import html
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from pypdf import PdfReader

from .models import AdaptedCV
from .renderer import HTMLCVRenderer
from .renderer import dynamic_professional_title


PDF_NOT_GENERATED = "PDF_NOT_GENERATED"
PDF_GENERATED = "PDF_GENERATED"
PDF_VALID = "PDF_VALID"
PDF_INVALID = "PDF_INVALID"
TOO_LONG = "TOO_LONG"


@dataclass(slots=True)
class PdfRenderResult:
    pdf_path: Path
    html_path: Path
    page_count: int = 0
    file_size_bytes: int = 0
    validation_status: str = PDF_NOT_GENERATED
    warnings: list[str] = field(default_factory=list)


PdfBackend = Callable[[Path, Path], None]


def render_cv_pdf(adapted_cv: AdaptedCV, output_path: str | Path, html_path: str | Path | None = None,
                  *, backend: PdfBackend | None = None) -> PdfRenderResult:
    """Render a validated AdaptedCV to HTML and a selectable-text A4 PDF."""
    if adapted_cv.validation_status != "VALID":
        raise ValueError("Only factually validated CVs can be rendered")
    pdf_path = Path(output_path)
    html_target = Path(html_path) if html_path else pdf_path.with_suffix(".html")
    pdf_path.parent.mkdir(parents=True, exist_ok=True)
    renderer = HTMLCVRenderer()
    attempts = ((0, adapted_cv), (1, adapted_cv), (2, _condensed_cv(adapted_cv)))
    last_result: PdfRenderResult | None = None
    for level, candidate in attempts:
        html_text = _with_pdf_density(renderer.render(candidate), level)
        html_target.write_text(html_text, encoding="utf-8")
        if pdf_path.exists():
            pdf_path.unlink()
        try:
            (backend or ReportLabPdfBackend(candidate, level))(html_target, pdf_path)
            last_result = validate_pdf(pdf_path, candidate, html_target)
        except Exception as exc:
            last_result = PdfRenderResult(pdf_path, html_target, validation_status=PDF_INVALID,
                                          warnings=[f"Falló el backend PDF: {exc}"])
        if last_result.page_count <= 2 and last_result.validation_status == PDF_VALID:
            if level:
                last_result.warnings.append(f"Se aplicó compresión de nivel {level} para respetar dos páginas.")
            return last_result
    assert last_result is not None
    if last_result.page_count > 2:
        last_result.validation_status = TOO_LONG
        last_result.warnings.append("El CV supera el máximo de dos páginas con la compresión segura disponible.")
    return last_result


def validate_pdf(pdf_path: str | Path, adapted_cv: AdaptedCV, html_path: str | Path | None = None) -> PdfRenderResult:
    pdf = Path(pdf_path); html = Path(html_path) if html_path else pdf.with_suffix(".html")
    warnings: list[str] = []
    if not pdf.is_file():
        return PdfRenderResult(pdf, html, validation_status=PDF_INVALID, warnings=["El archivo PDF no existe."])
    size = pdf.stat().st_size
    try:
        reader = PdfReader(str(pdf)); pages = len(reader.pages)
        text = "\n".join(page.extract_text() or "" for page in reader.pages)
    except Exception as exc:
        return PdfRenderResult(pdf, html, file_size_bytes=size, validation_status=PDF_INVALID,
                               warnings=[f"No se pudo leer el PDF: {exc}"])
    if size < 1_000: warnings.append("El PDF es demasiado pequeño.")
    if not text.strip(): warnings.append("El PDF no contiene texto extraíble.")
    name = adapted_cv.personal.get("name", "").strip()
    if name and name.casefold() not in text.casefold(): warnings.append("No se encontró el nombre del candidato.")
    companies = [section.company for section in adapted_cv.experience_sections]
    if companies and not any(company.casefold() in text.casefold() for company in companies):
        warnings.append("No se encontró ninguna experiencia seleccionada.")
    if any(marker in text.casefold() for marker in ("about:blank", "page not found", "error 404")):
        warnings.append("El PDF parece contener un error de renderizado.")
    for key in ("linkedin", "github", "email"):
        expected = adapted_cv.personal.get(key, "").strip()
        if expected and expected.casefold() not in text.casefold():
            warnings.append(f"No se encontró el contacto factual: {key}.")
    status = PDF_VALID if not warnings and pages <= 2 else TOO_LONG if pages > 2 else PDF_INVALID
    return PdfRenderResult(pdf, html, pages, size, status, warnings)


class EdgePdfBackend:
    def __init__(self, executable: str | Path | None = None):
        self.executable = Path(executable) if executable else _find_edge()

    def __call__(self, html_path: Path, pdf_path: Path) -> None:
        with tempfile.TemporaryDirectory(prefix=".edge-", dir=pdf_path.parent) as profile:
            command = [str(self.executable), "--headless=new", "--disable-gpu", "--disable-software-rasterizer",
                       "--disable-gpu-compositing", "--no-first-run", "--no-pdf-header-footer",
                       f"--user-data-dir={profile}", f"--print-to-pdf={pdf_path.resolve()}", html_path.resolve().as_uri()]
            completed = subprocess.run(command, capture_output=True, text=True, timeout=45, check=False)
        if completed.returncode != 0 or not pdf_path.is_file():
            detail = (completed.stderr or completed.stdout or "sin detalle").strip()
            raise RuntimeError(f"Microsoft Edge no pudo generar el PDF: {detail}")


def _find_edge() -> Path:
    candidates = [
        Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"),
        Path(r"C:\Program Files\Microsoft\Edge\Application\msedge.exe"),
    ]
    command = shutil.which("msedge")
    if command: candidates.insert(0, Path(command))
    match = next((path for path in candidates if path.is_file()), None)
    if match is None:
        raise RuntimeError("Microsoft Edge no está instalado o no se encontró msedge.exe")
    return match


class ReportLabPdfBackend:
    """ATS-friendly, selectable-text PDF composed from the same validated CV as the HTML."""
    def __init__(self, cv: AdaptedCV, density: int = 0):
        self.cv, self.density = cv, density

    def __call__(self, html_path: Path, pdf_path: Path) -> None:
        from reportlab.lib import colors
        from reportlab.lib.enums import TA_CENTER
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
        from reportlab.lib.units import mm
        from reportlab.platypus import KeepTogether, ListFlowable, ListItem, Paragraph, SimpleDocTemplate, Spacer

        density = self.density
        body_size = (10.2, 9.8, 9.5)[density]
        leading = (13.2, 12.2, 11.4)[density]
        gap = (4.0, 2.5, 1.5)[density]
        navy = colors.HexColor("#243B64"); grey = colors.HexColor("#46566E")
        sample = getSampleStyleSheet()
        body = ParagraphStyle("CVBody", parent=sample["BodyText"], fontName="Helvetica",
                              fontSize=body_size, leading=leading, textColor=colors.HexColor("#172033"),
                              spaceAfter=gap)
        heading = ParagraphStyle("CVHeading", parent=body, fontName="Helvetica-Bold", fontSize=(12, 11.5, 11)[density],
                                 leading=(15, 14, 13)[density], textColor=navy, spaceBefore=(9, 6, 4)[density],
                                 spaceAfter=(4, 3, 2)[density], keepWithNext=True)
        name_style = ParagraphStyle("CVName", parent=body, fontName="Helvetica-Bold", fontSize=(22, 21, 20)[density],
                                    leading=24, textColor=navy, alignment=TA_CENTER, spaceAfter=2)
        title_style = ParagraphStyle("CVTitle", parent=body, fontSize=12, leading=14, textColor=navy,
                                     alignment=TA_CENTER, spaceAfter=2)
        contact_style = ParagraphStyle("CVContact", parent=body, fontSize=8.8, leading=11, textColor=grey,
                                       alignment=TA_CENTER, spaceAfter=(8, 6, 4)[density])
        item_head = ParagraphStyle("CVItemHead", parent=body, fontName="Helvetica-Bold", spaceAfter=0, keepWithNext=True)
        meta = ParagraphStyle("CVMeta", parent=body, fontSize=9, leading=11, textColor=grey, spaceAfter=2, keepWithNext=True)
        doc = SimpleDocTemplate(str(pdf_path), pagesize=A4, leftMargin=14 * mm, rightMargin=14 * mm,
                                topMargin=12 * mm, bottomMargin=12 * mm,
                                title=f"CV - {self.cv.personal.get('name', '')}", author=self.cv.personal.get("name", ""))
        story = [Paragraph(_xml(self.cv.personal.get("name", "")), name_style),
                 Paragraph(_xml(dynamic_professional_title(self.cv)), title_style),
                 Paragraph(_contact_markup(self.cv.personal), contact_style)]

        def section(title: str): story.append(Paragraph(_xml(title.upper()), heading))
        def bullets(values):
            if values:
                story.append(ListFlowable([ListItem(Paragraph(_xml(value.text), body), leftIndent=8)
                                           for value in values], bulletType="bullet", leftIndent=12,
                                          bulletFontName="Helvetica", bulletFontSize=6, spaceAfter=gap))

        section("Perfil profesional"); story.append(Paragraph(_xml(self.cv.professional_summary), body))
        if self.cv.experience_sections:
            section("Experiencia")
            for value in self.cv.experience_sections:
                block = [Paragraph(f"{_xml(value.role)} · {_xml(value.company)}", item_head),
                         Paragraph(f"{_xml(value.start_date)} – {_xml(value.end_date)}", meta)]
                bullet_flow = ListFlowable([ListItem(Paragraph(_xml(bullet.text), body), leftIndent=8)
                                            for bullet in value.bullets], bulletType="bullet", leftIndent=12,
                                           bulletFontSize=6, spaceAfter=gap)
                block.append(bullet_flow)
                if value.technologies: block.append(Paragraph("Tecnologías: " + _xml(" · ".join(value.technologies)), meta))
                story.append(KeepTogether(block)); story.append(Spacer(1, gap))
        if self.cv.project_sections:
            section("Proyectos destacados")
            for value in self.cv.project_sections:
                block = [Paragraph(_xml(value.name), item_head)]
                if value.description: block.append(Paragraph(_xml(value.description), body))
                if value.bullets:
                    block.append(ListFlowable([ListItem(Paragraph(_xml(bullet.text), body), leftIndent=8)
                                               for bullet in value.bullets], bulletType="bullet", leftIndent=12,
                                              bulletFontSize=6, spaceAfter=gap))
                if value.technologies: block.append(Paragraph("Tecnologías: " + _xml(" · ".join(value.technologies)), meta))
                for link in value.links: block.append(Paragraph(_link_markup(link), meta))
                story.append(KeepTogether(block)); story.append(Spacer(1, gap))
        if self.cv.skills:
            section("Habilidades"); story.append(Paragraph(_xml(" · ".join(self.cv.skills)), body))
        if self.cv.education:
            section("Educación")
            for value in self.cv.education:
                story.append(KeepTogether([Paragraph(_xml(value.program), item_head),
                    Paragraph(_xml(" · ".join(filter(None, (value.institution, value.status, value.dates)))), meta)]))
        if self.cv.courses:
            section("Cursos y certificaciones")
            for value in self.cv.courses:
                story.append(KeepTogether([Paragraph(_xml(value.program), item_head),
                    Paragraph(_xml(" · ".join(filter(None, (value.institution, value.status)))), meta)]))
        if self.cv.languages:
            section("Idiomas"); story.append(Paragraph(_xml(" · ".join(
                f"{value.language}: {value.level}" for value in self.cv.languages)), body))
        doc.build(story)


def _xml(value: str) -> str:
    return html.escape(str(value), quote=True)


def _contact_markup(personal: dict[str, str]) -> str:
    values = []
    for key in ("location", "email", "linkedin", "github"):
        value = personal.get(key, "").strip()
        if not value: continue
        if key in {"linkedin", "github"}:
            href = value if value.startswith(("http://", "https://")) else "https://" + value
            values.append(f'<link href="{_xml(href)}">{_xml(value)}</link>')
        elif key == "email":
            values.append(f'<link href="mailto:{_xml(value)}">{_xml(value)}</link>')
        else: values.append(_xml(value))
    return " · ".join(values)


def _link_markup(value: str) -> str:
    href = value if value.startswith(("http://", "https://")) else "https://" + value
    return f'<link href="{_xml(href)}">{_xml(value)}</link>'


def _with_pdf_density(document: str, level: int) -> str:
    css = ""
    body_class = "pdf-normal"
    if level == 1:
        body_class = "pdf-compact"
        css = "body{font-size:10pt;line-height:1.28} h2{margin:10px 0 5px}.entry{margin-bottom:6px} li{margin-bottom:1px}"
    elif level >= 2:
        body_class = "pdf-condensed"
        css = "body{font-size:9.5pt;line-height:1.22} h1{font-size:21pt} h2{font-size:11pt;margin:8px 0 4px}.entry{margin-bottom:5px} ul{margin-top:2px;margin-bottom:2px} li{margin-bottom:0}"
    document = document.replace("</style>", f"{css}</style>", 1)
    return document.replace("<body>", f'<body class="{body_class}">', 1)


def _condensed_cv(cv: AdaptedCV) -> AdaptedCV:
    candidate = copy.deepcopy(cv)
    for index, section in enumerate(candidate.experience_sections):
        maximum = 3 if index == 0 else 2 if index == 1 else 1
        section.bullets = section.bullets[:maximum]
    candidate.project_sections = candidate.project_sections[:2]
    for section in candidate.project_sections:
        section.bullets = section.bullets[:2]
    candidate.courses = candidate.courses[:3]
    return candidate
