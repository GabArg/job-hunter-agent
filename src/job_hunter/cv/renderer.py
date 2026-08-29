from __future__ import annotations

import html
from pathlib import Path

from .models import AdaptedCV


class HTMLCVRenderer:
    def __init__(self, template_path: str | Path | None = None):
        self.template_path = Path(template_path) if template_path else Path(__file__).parent / "templates" / "classic.html"

    def render(self, cv: AdaptedCV) -> str:
        if cv.validation_status != "VALID":
            raise ValueError("Only factually validated CVs can be rendered")
        template = self.template_path.read_text(encoding="utf-8")
        replacements = {
            "{{NAME}}": _e(cv.personal.get("name", "")),
            "{{HEADLINE}}": _e(cv.personal.get("headline", "")),
            "{{CONTACT}}": _contact(cv.personal),
            "{{SUMMARY}}": _e(cv.professional_summary),
            "{{SKILLS}}": ", ".join(_e(skill) for skill in cv.skills),
            "{{EXPERIENCE}}": _experience(cv),
            "{{PROJECTS}}": _projects(cv),
            "{{EDUCATION}}": _education(cv),
            "{{LANGUAGES}}": ", ".join(
                f"{_e(item.language)}: {_e(item.level)}" for item in cv.languages
            ),
        }
        for marker, value in replacements.items():
            template = template.replace(marker, value)
        return template

    def render_to_file(self, cv: AdaptedCV, output_path: str | Path) -> Path:
        target = Path(output_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(self.render(cv), encoding="utf-8")
        return target


def _experience(cv: AdaptedCV) -> str:
    return "".join(
        f'<section class="entry"><div class="entry-head"><strong>{_e(section.role)}</strong>'
        f'<span>{_e(section.start_date)} – {_e(section.end_date)}</span></div>'
        f'<div class="organization">{_e(section.company)}</div>{_bullets(section.bullets)}'
        f'<div class="tech">{", ".join(_e(value) for value in section.technologies)}</div></section>'
        for section in cv.experience_sections
    )


def _projects(cv: AdaptedCV) -> str:
    if not cv.project_sections:
        return ""
    body = "".join(
        f'<section class="entry"><strong>{_e(section.name)}</strong><div>{_e(section.description)}</div>'
        f'{_bullets(section.bullets)}<div class="tech">{", ".join(_e(value) for value in section.technologies)}</div></section>'
        for section in cv.project_sections
    )
    return f"<h2>Proyectos</h2>{body}"


def _education(cv: AdaptedCV) -> str:
    return "".join(
        f'<section class="entry"><div class="entry-head"><strong>{_e(item.program)}</strong>'
        f'<span>{_e(item.dates)}</span></div><div>{_e(item.institution)}'
        f' · {_e(item.status)}</div></section>' for item in cv.education
    )


def _bullets(bullets) -> str:
    return "<ul>" + "".join(f"<li>{_e(bullet.text)}</li>" for bullet in bullets) + "</ul>"


def _contact(personal: dict[str, str]) -> str:
    keys = ("location", "linkedin", "github")
    return " · ".join(_e(personal.get(key, "")) for key in keys if personal.get(key))


def _e(value: str) -> str:
    return html.escape(str(value), quote=True)
