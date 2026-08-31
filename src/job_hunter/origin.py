from __future__ import annotations

from datetime import datetime
from typing import Any, Iterable

from .discovery.matching import parse_datetime

AUTOMATIC_DISCOVERY = "AUTOMATIC_DISCOVERY"
MANUAL_URL = "MANUAL_URL"
MANUAL_TEXT = "MANUAL_TEXT"
MANUAL_FORM = "MANUAL_FORM"
UNKNOWN = "UNKNOWN"
MANUAL_ORIGINS = {MANUAL_URL, MANUAL_TEXT, MANUAL_FORM}
AUTOMATIC_SOURCE_PREFIXES = {
    "remoteok", "arbeitnow", "greenhouse", "lever", "ashby", "workable",
    "smartrecruiters", "recruitee", "generic",
}


def get_job_origin(row: dict[str, Any]) -> str:
    """Return the initial origin using explicit import metadata before source heuristics."""
    method = str(row.get("import_method") or "").upper()
    source = str(row.get("source") or "").casefold()
    url = str(row.get("url") or "").casefold()
    imported = bool(row.get("imported_manually"))
    if method == "PASTED_TEXT" or url.startswith("manual://") or source == "manual:text": return MANUAL_TEXT
    if method == "MANUAL_FORM" or source == "manual:user": return MANUAL_FORM
    if method in {"PUBLIC_URL", "MANUAL_URL"}: return MANUAL_URL
    if imported or source.startswith("manual:"):
        return MANUAL_URL if url.startswith(("http://", "https://")) else UNKNOWN
    if is_automatic_source(source): return AUTOMATIC_DISCOVERY
    return UNKNOWN


def was_discovered_automatically(row: dict[str, Any]) -> bool:
    return is_automatic_source(str(row.get("source") or ""))


def is_automatic_source(source: str) -> bool:
    prefix = source.casefold().split(":", 1)[0].strip()
    return prefix in AUTOMATIC_SOURCE_PREFIXES


def origin_label(origin: str) -> str:
    return {AUTOMATIC_DISCOVERY: "Discovery automático", MANUAL_URL: "Importada manualmente · URL",
            MANUAL_TEXT: "Importada manualmente · Texto", MANUAL_FORM: "Importada manualmente · Formulario",
            UNKNOWN: "Origen no determinado"}.get(origin, "Origen no determinado")


def filter_jobs_by_origin(rows: Iterable[dict[str, Any]], selected: str) -> list[dict[str, Any]]:
    values = list(rows)
    if selected == "ALL": return values
    if selected == "MANUAL": return [row for row in values if get_job_origin(row) in MANUAL_ORIGINS]
    return [row for row in values if get_job_origin(row) == selected]


def origin_summary(rows: Iterable[dict[str, Any]], now: datetime | None = None) -> dict[str, int]:
    reference = (now or datetime.now().astimezone()).astimezone()
    values = list(rows)
    def local_date(row):
        value = parse_datetime(row.get("imported_at") or row.get("first_seen_at"))
        return value.astimezone().date() if value else None
    origins = [(row, get_job_origin(row), local_date(row)) for row in values]
    return {
        "automatic_total": sum(origin == AUTOMATIC_DISCOVERY for _, origin, _ in origins),
        "manual_total": sum(origin in MANUAL_ORIGINS for _, origin, _ in origins),
        "unknown_total": sum(origin == UNKNOWN for _, origin, _ in origins),
        "automatic_today": sum(origin == AUTOMATIC_DISCOVERY and date == reference.date() for _, origin, date in origins),
        "manual_today": sum(origin in MANUAL_ORIGINS and date == reference.date() for _, origin, date in origins),
        "manual_week": sum(origin in MANUAL_ORIGINS and date and date.isocalendar()[:2] == reference.date().isocalendar()[:2]
                           for _, origin, date in origins),
    }


def jobs_created_by_run(rows: Iterable[dict[str, Any]], run: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not run: return []
    started, finished = parse_datetime(run.get("started_at")), parse_datetime(run.get("finished_at"))
    if not started: return []
    result = []
    for row in rows:
        first_seen = parse_datetime(row.get("first_seen_at"))
        if (get_job_origin(row) == AUTOMATIC_DISCOVERY and first_seen and first_seen >= started
                and (finished is None or first_seen <= finished)):
            result.append(row)
    return sorted(result, key=lambda row: (str(row.get("first_seen_at") or ""), int(row.get("id") or 0)))
