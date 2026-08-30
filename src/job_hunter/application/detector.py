from __future__ import annotations

import re
import unicodedata
from typing import Any
from urllib.parse import urlparse

from .models import ApplicationDetection, ApplicationMethod, JobLanguage

EMAIL_RE = re.compile(r"(?<![\w.+-])([A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,})(?![\w-])", re.I)
EMAIL_SIGNALS = (
    "enviar cv", "enviar tu cv", "envia tu cv", "envianos tu cv", "manda tu cv",
    "mandar cv", "compartinos tu cv", "comparti tu cv", "postulate enviando tu cv",
    "postulaciones a", "postulaciones:", "send resume to", "send cv to",
    "email your resume", "apply by email",
)
RECRUITING_CONTEXT = (
    "cv", "curriculum", "resume", "postulacion", "postulaciones", "postular",
    "postulate", "apply", "recruitment", "recruiting", "seleccion",
)
LINK_SIGNALS = ("apply at", "apply here", "postulate aquí", "postulate aqui", "postularse aquí", "postularse aqui", "aplicar aquí", "aplicar aqui")
NON_RECRUITING_LOCALS = {"support", "soporte", "help", "ayuda", "security", "seguridad", "privacy", "privacidad", "noreply", "no-reply", "info"}
INSTRUCTION_SIGNALS = {
    "remuneración pretendida": ("remuneración pretendida", "remuneracion pretendida", "salary expectation", "expected salary"),
    "referencia del puesto": ("referencia", "reference code", "job reference"),
    "disponibilidad": ("disponibilidad", "availability"), "ubicación": ("ubicación", "ubicacion", "location"),
    "portfolio": ("portfolio", "portafolio"), "GitHub": ("github",), "LinkedIn": ("linkedin",),
    "carta de presentación": ("carta de presentación", "carta de presentacion", "cover letter"),
    "CV en inglés": ("cv en inglés", "cv en ingles", "resume in english"),
    "CV en español": ("cv en español", "cv en espanol"), "formato PDF": ("pdf",), "formato DOCX": ("docx", "word format"),
}


def detect_application_channel(description: str, url: str = "", raw_data: dict[str, Any] | None = None) -> ApplicationDetection:
    raw_text = " ".join(_flatten(raw_data or {})); text = f"{description or ''} {raw_text}".strip()
    lowered = _normalize_text(text); candidates = extract_recruiting_emails(text)
    email_signal = any(signal in lowered for signal in EMAIL_SIGNALS)
    contextual_email = len(candidates) == 1 and _has_recruiting_context(lowered, candidates[0])
    link_signal = any(signal in lowered for signal in LINK_SIGNALS)
    valid_link = _valid_http_url(url)
    has_email = bool(candidates and (email_signal or contextual_email))
    if has_email and link_signal and valid_link: method = ApplicationMethod.LINK_EMAIL
    elif has_email: method = ApplicationMethod.EMAIL
    elif valid_link: method = ApplicationMethod.LINK
    else: method = ApplicationMethod.UNKNOWN
    ambiguous = len(candidates) > 1
    email = candidates[0] if len(candidates) == 1 else None
    instructions = extract_application_instructions(text)
    if ambiguous: instructions.append(f"Revisar destinatario: se detectaron {len(candidates)} emails de recruiting")
    return ApplicationDetection(method, email, url if valid_link else None, instructions, candidates, ambiguous,
                                _required_subject(text), detect_language(text))


def extract_recruiting_emails(text: str) -> list[str]:
    found = []
    for email in EMAIL_RE.findall(text or ""):
        normalized = email.lower().rstrip(".,;:")
        local = normalized.split("@", 1)[0]
        if local in NON_RECRUITING_LOCALS or any(token in local for token in ("support", "soporte", "noreply")): continue
        if normalized not in found: found.append(normalized)
    return found


def extract_application_instructions(text: str) -> list[str]:
    lowered = _normalize_text(text or ""); results = []
    for label, signals in INSTRUCTION_SIGNALS.items():
        if any(_normalize_text(signal) in lowered for signal in signals): results.append(label)
    subject = _required_subject(text)
    if subject: results.append(f"Asunto obligatorio: {subject}")
    return results


def detect_language(text: str) -> JobLanguage:
    lowered = f" {text.casefold()} "
    spanish = sum(token in lowered for token in (" buscamos ", " requisitos ", " experiencia ", " enviar ", " postulación ", " puesto ", " trabajo "))
    english = sum(token in lowered for token in (" we are ", " requirements ", " experience ", " apply ", " position ", " resume ", " role "))
    if spanish > english and spanish >= 2: return JobLanguage.SPANISH
    if english > spanish and english >= 2: return JobLanguage.ENGLISH
    return JobLanguage.UNKNOWN


def _required_subject(text: str) -> str | None:
    match = re.search(
        r"(?:asunto|subject)\s*(?:obligatorio|required)?\s*[:\-]\s*"
        r"([^\n.;]{3,100}?)(?=\s+(?:se\s+(?:valoran?|requieren?|buscan?)|buscamos|requisitos?|enviar|send)\b|[\n.;]|$)",
        text or "", re.I,
    )
    return match.group(1).strip() if match else None


def _valid_http_url(value: str) -> bool:
    try: parsed = urlparse(value); return parsed.scheme in {"http", "https"} and bool(parsed.netloc)
    except ValueError: return False


def _has_recruiting_context(text: str, email: str) -> bool:
    position = text.find(email.casefold())
    if position < 0:
        return False
    nearby = text[max(0, position - 180):position + len(email) + 80]
    return any(re.search(rf"(?<!\w){re.escape(signal)}(?!\w)", nearby) for signal in RECRUITING_CONTEXT)


def _normalize_text(value: str) -> str:
    decomposed = unicodedata.normalize("NFKD", value.casefold())
    return "".join(character for character in decomposed if not unicodedata.combining(character))


def _flatten(value: Any):
    if isinstance(value, dict):
        for child in value.values(): yield from _flatten(child)
    elif isinstance(value, list):
        for child in value: yield from _flatten(child)
    elif isinstance(value, (str, int, float)): yield str(value)
