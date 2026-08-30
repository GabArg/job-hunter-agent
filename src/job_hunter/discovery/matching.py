from __future__ import annotations

import re
import unicodedata
from datetime import datetime, timedelta, timezone

from .models import RawJob
from ..semantics import roles_match

INCOMPATIBLE_REGIONS = (
    r"\bus only\b", r"\bu\.s\. only\b", r"\bunited states only\b",
    r"\beu only\b", r"\beuropean union only\b", r"\buk only\b",
    r"\bunited kingdom only\b", r"\bcanada only\b",
    r"\bbrazil only\b", r"\bbrasil only\b", r"\bsolo brasil\b",
    r"\bmexico only\b", r"\bsolo mexico\b", r"\bcolombia only\b", r"\bsolo colombia\b",
    r"\bchile only\b", r"\bperu only\b",
)
ARGENTINA_LOCATIONS = (
    "argentina", "buenos aires", "caba", "amba", "provincia de buenos aires",
    "remote argentina", "remote latam", "latin america", "latam", "south america",
    "remote anywhere in latam",
)


def normalized(value: str) -> str:
    decomposed = unicodedata.normalize("NFKD", value or "")
    return re.sub(r"\s+", " ", "".join(c for c in decomposed if not unicodedata.combining(c)).lower()).strip()


def title_matches(title: str, aliases: list[str], description: str = "") -> bool:
    candidate = normalized(title)
    return any(
        _phrase_in(candidate, normalized(alias)) or roles_match(title, alias, description)
        for alias in aliases if alias.strip()
    )


def geography_compatible(raw: RawJob, preferred_locations: list[str]) -> tuple[bool, str | None]:
    evidence = normalized(f"{raw.location} {raw.work_mode} {raw.description}")
    argentina_explicit = any(marker in evidence for marker in ARGENTINA_LOCATIONS) or bool(re.search(r"(?<!\w)ar(?!\w)", evidence))
    if not argentina_explicit:
        for pattern in INCOMPATIBLE_REGIONS:
            if re.search(pattern, evidence):
                return False, f"Restricción geográfica incompatible: {re.search(pattern, evidence).group(0)}"
    preferences = [normalized(value) for value in preferred_locations]
    wants_argentina = any(value in ARGENTINA_LOCATIONS for value in preferences)
    if wants_argentina:
        if argentina_explicit:
            return True, None
        if "remote" in evidence:
            return False, "Remote sin confirmación de disponibilidad para Argentina/LATAM"
        return False, "Ubicación fuera del foco Argentina/LATAM"
    if preferences and not any(value in evidence for value in preferences):
        return False, "Ubicación no preferida"
    return True, None


def is_fresh(published_at: str | None, max_age_days: int | None, now: datetime | None = None) -> bool:
    if not published_at or max_age_days is None:
        return True
    published = parse_datetime(published_at)
    if published is None:
        return True
    reference = now or datetime.now(timezone.utc)
    return published >= reference - timedelta(days=max_age_days)


def is_priority_fresh(published_at: str | None, days: int = 3, now: datetime | None = None) -> bool:
    if not published_at:
        return False
    published = parse_datetime(published_at)
    if published is None:
        return False
    return published >= (now or datetime.now(timezone.utc)) - timedelta(days=days)


ANALYTIC_COMMERCIAL_SIGNALS = (
    "analisis", "analytics", "datos", "data", "kpi", "pricing", "precios", "margen",
    "rentabilidad", "reporting", "reporte", "forecast", "excel", "power bi", "bi ",
    "performance", "costos", "costes",
)
SALES_COMMERCIAL_SIGNALS = (
    "venta directa", "captacion", "prospeccion", "comision", "cartera comercial",
    "ejecutivo comercial", "vendedor", "cumplimiento de cuota", "cold call",
)


def description_relevant(title: str, description: str) -> bool:
    """Reject sales-heavy commercial roles while retaining analytical commercial roles."""
    title_text, body = normalized(title), normalized(description)
    commercial = any(term in title_text for term in ("analista comercial", "commercial analyst"))
    if not commercial:
        return True
    analytic = sum(signal in body for signal in ANALYTIC_COMMERCIAL_SIGNALS)
    sales = sum(signal in body for signal in SALES_COMMERCIAL_SIGNALS)
    return analytic >= 1 and analytic >= sales


def parse_datetime(value: str | int | float | None) -> datetime | None:
    if value in (None, ""):
        return None
    try:
        if isinstance(value, (int, float)) or str(value).isdigit():
            timestamp = float(value)
            if timestamp > 100_000_000_000:  # ATS such as Lever publish Unix milliseconds.
                timestamp /= 1000
            return datetime.fromtimestamp(timestamp, tz=timezone.utc)
        text = str(value).strip().replace("Z", "+00:00")
        if text.upper().endswith(" UTC"):
            text = text[:-4] + "+00:00"
        parsed = datetime.fromisoformat(text)
        return parsed.replace(tzinfo=parsed.tzinfo or timezone.utc).astimezone(timezone.utc)
    except (ValueError, TypeError, OSError):
        return None


def normalize_datetime(value: str | int | float | None) -> str | None:
    parsed = parse_datetime(value)
    return parsed.isoformat(timespec="seconds") if parsed else None


def _phrase_in(title: str, phrase: str) -> bool:
    return bool(re.search(rf"(?<!\w){re.escape(phrase)}(?!\w)", title))
