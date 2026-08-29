from __future__ import annotations

import re
import unicodedata
from datetime import datetime, timedelta, timezone

from .models import RawJob

INCOMPATIBLE_REGIONS = (
    r"\bus only\b", r"\bu\.s\. only\b", r"\bunited states only\b",
    r"\beu only\b", r"\beuropean union only\b", r"\buk only\b",
    r"\bunited kingdom only\b", r"\bcanada only\b",
)
ARGENTINA_LOCATIONS = (
    "argentina", "buenos aires", "caba", "amba", "provincia de buenos aires",
    "remote argentina", "remote latam", "latin america", "latam",
)


def normalized(value: str) -> str:
    decomposed = unicodedata.normalize("NFKD", value or "")
    return re.sub(r"\s+", " ", "".join(c for c in decomposed if not unicodedata.combining(c)).lower()).strip()


def title_matches(title: str, aliases: list[str]) -> bool:
    candidate = normalized(title)
    return any(_phrase_in(candidate, normalized(alias)) for alias in aliases if alias.strip())


def geography_compatible(raw: RawJob, preferred_locations: list[str]) -> tuple[bool, str | None]:
    evidence = normalized(f"{raw.location} {raw.work_mode} {raw.description}")
    for pattern in INCOMPATIBLE_REGIONS:
        if re.search(pattern, evidence):
            return False, f"Restricción geográfica incompatible: {re.search(pattern, evidence).group(0)}"
    preferences = [normalized(value) for value in preferred_locations]
    wants_argentina = any(value in ARGENTINA_LOCATIONS for value in preferences)
    if wants_argentina:
        if any(marker in evidence for marker in ARGENTINA_LOCATIONS):
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


def parse_datetime(value: str | int | float | None) -> datetime | None:
    if value in (None, ""):
        return None
    try:
        if isinstance(value, (int, float)) or str(value).isdigit():
            timestamp = float(value)
            if timestamp > 100_000_000_000:  # ATS such as Lever publish Unix milliseconds.
                timestamp /= 1000
            return datetime.fromtimestamp(timestamp, tz=timezone.utc)
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return parsed.replace(tzinfo=parsed.tzinfo or timezone.utc).astimezone(timezone.utc)
    except (ValueError, TypeError, OSError):
        return None


def _phrase_in(title: str, phrase: str) -> bool:
    return bool(re.search(rf"(?<!\w){re.escape(phrase)}(?!\w)", title))
