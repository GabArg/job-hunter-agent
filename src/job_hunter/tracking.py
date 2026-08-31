from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
from statistics import mean, median
from typing import Any, Iterable
from urllib.parse import urlsplit

from .discovery.matching import parse_datetime

ACTIVE_STAGES = {
    "APPLIED", "RECRUITER_VIEWED", "RECRUITER_CONTACT", "HR_INTERVIEW", "TECH_INTERVIEW",
    "BUSINESS_INTERVIEW", "FINAL_INTERVIEW", "ASSESSMENT", "OFFER",
}
CLOSED_STAGES = {"HIRED", "REJECTED", "WITHDRAWN", "CLOSED_NO_RESPONSE"}
RESPONSE_STAGES = {
    "RECRUITER_CONTACT", "HR_INTERVIEW", "TECH_INTERVIEW", "BUSINESS_INTERVIEW",
    "FINAL_INTERVIEW", "ASSESSMENT", "OFFER", "HIRED", "REJECTED", "WITHDRAWN",
}
INTERVIEW_STAGES = {"HR_INTERVIEW", "TECH_INTERVIEW", "BUSINESS_INTERVIEW", "FINAL_INTERVIEW"}
FINALIST_STAGES = {"FINAL_INTERVIEW", "OFFER", "HIRED"}
OFFER_STAGES = {"OFFER", "HIRED"}


def analytics_snapshot(jobs: Iterable[dict[str, Any]], histories: dict[int, list[dict[str, Any]]],
                       now: datetime | None = None) -> dict[str, Any]:
    reference = now or datetime.now(timezone.utc)
    applied = [row for row in jobs if row.get("application_stage") != "NOT_APPLIED" or row.get("applied_at")]
    reached = {int(row["id"]): _reached_stages(row, histories.get(int(row["id"]), [])) for row in applied}
    total = len(applied)
    responses = sum(bool(values & RESPONSE_STAGES) for values in reached.values())
    interviews = sum(bool(values & INTERVIEW_STAGES) for values in reached.values())
    offers = sum(bool(values & OFFER_STAGES) for values in reached.values())
    hires = sum("HIRED" in values for values in reached.values())
    applied_dates = [_dt(row.get("applied_at")) for row in applied]
    kpis = {
        "applications_today": sum(value and value.date() == reference.date() for value in applied_dates),
        "applications_week": sum(value and value.isocalendar()[:2] == reference.isocalendar()[:2] for value in applied_dates),
        "applications_month": sum(value and (value.year, value.month) == (reference.year, reference.month) for value in applied_dates),
        "active_processes": sum(row.get("application_stage") in ACTIVE_STAGES for row in applied),
        "responses": responses, "interviews": interviews, "offers": offers, "hires": hires,
    }
    rates = {"response_rate": _rate(responses, total), "interview_rate": _rate(interviews, total),
             "offer_rate": _rate(offers, total), "hire_rate": _rate(hires, total)}
    funnel = {"Postuladas": total, "Respuestas": responses, "Entrevistas": interviews,
              "Finalistas": sum(bool(v & FINALIST_STAGES) for v in reached.values()),
              "Ofertas": offers, "Contrataciones": hires}
    return {
        "kpis": kpis, "rates": rates, "funnel": funnel,
        "daily": _daily(applied), "weekly": _weekly(applied, reached),
        "by_role": _grouped(applied, reached, lambda row: detect_role_family(row.get("title", ""))),
        "by_source": _grouped(applied, reached, normalize_source),
        "by_channel": _grouped(applied, reached, lambda row: row.get("application_channel_used") or row.get("selected_application_channel") or row.get("application_method") or "UNKNOWN"),
        "by_score": _grouped(applied, reached, lambda row: score_bucket(float(row.get("score") or 0))),
        "timings": _timings(applied, histories),
    }


def tracking_row(row: dict[str, Any], now: datetime | None = None) -> dict[str, Any]:
    reference = now or datetime.now(timezone.utc)
    updated = _dt(row.get("stage_updated_at") or row.get("applied_at"))
    applied = _dt(row.get("applied_at"))
    days_stage = max(0, (reference.date() - updated.date()).days) if updated else None
    days_applied = max(0, (reference.date() - applied.date()).days) if applied else None
    return {**row, "days_in_stage": days_stage, "days_since_applied": days_applied,
            "no_response_band": no_response_band(row.get("application_stage"), days_applied)}


def no_response_band(stage: str | None, days: int | None) -> str | None:
    if stage not in {"APPLIED", "RECRUITER_VIEWED"} or days is None: return None
    return "0–4 días" if days < 5 else "5–9 días" if days < 10 else "10+ días"


def detect_role_family(title: str) -> str:
    value = title.casefold()
    rules = (
        ("AI Automation", ("ai automation", "automatización", "automation", "generative ai")),
        ("Data Engineering", ("data engineer", "analytics engineer", "ingeniería de datos")),
        ("Data Science", ("data scientist", "data science", "ciencia de datos")),
        ("BI Analyst", ("bi analyst", "business intelligence", "analista bi")),
        ("Business Analyst", ("business analyst", "analista de negocio")),
        ("Data Analyst", ("data analyst", "data analytics", "analista de datos")),
        ("Cloud", ("cloud", "aws", "gcp", "azure")),
    )
    return next((label for label, terms in rules if any(term in value for term in terms)), "Otros")


def normalize_source(row: dict[str, Any]) -> str:
    source = str(row.get("source") or "").casefold()
    url = str(row.get("url") or "").casefold()
    text = f"{source} {url}"
    labels = (("LinkedIn/manual", ("linkedin", "manual", "pasted")), ("Greenhouse", ("greenhouse",)),
              ("Lever", ("lever",)), ("Ashby", ("ashby",)), ("Workable", ("workable",)),
              ("SmartRecruiters", ("smartrecruiters",)), ("Recruitee", ("recruitee",)),
              ("RemoteOK", ("remoteok",)), ("Arbeitnow", ("arbeitnow",)), ("Email", ("email",)))
    found = next((label for label, terms in labels if any(term in text for term in terms)), None)
    return found or (urlsplit(url).hostname or source or "Otros")


def score_bucket(score: float) -> str:
    if score < 55: return "<55"
    if score < 65: return "55–64"
    if score < 75: return "65–74"
    if score < 85: return "75–84"
    return "85–100"


def _reached_stages(row, history):
    return {str(row.get("application_stage") or "NOT_APPLIED"), *(str(event["to_stage"]) for event in history)}


def _grouped(rows, reached, key):
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows: groups[str(key(row))].append(row)
    result = []
    for name, values in sorted(groups.items()):
        responses = sum(bool(reached[int(row["id"])] & RESPONSE_STAGES) for row in values)
        interviews = sum(bool(reached[int(row["id"])] & INTERVIEW_STAGES) for row in values)
        result.append({"group": name, "applications": len(values), "responses": responses,
                       "interviews": interviews, "response_rate": _rate(responses, len(values)),
                       "interview_rate": _rate(interviews, len(values))})
    return result


def _daily(rows):
    counts: dict[str, int] = defaultdict(int)
    for row in rows:
        value = _dt(row.get("applied_at"))
        if value: counts[value.date().isoformat()] += 1
    return [{"date": key, "applications": counts[key]} for key in sorted(counts)]


def _weekly(rows, reached):
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        value = _dt(row.get("applied_at"))
        if value: groups[f"{value.isocalendar().year}-W{value.isocalendar().week:02d}"].append(row)
    result = []
    for week, values in sorted(groups.items()):
        result.append({"week": week, "applications": len(values),
            "responses": sum(bool(reached[int(r["id"])] & RESPONSE_STAGES) for r in values),
            "interviews": sum(bool(reached[int(r["id"])] & INTERVIEW_STAGES) for r in values),
            "offers": sum(bool(reached[int(r["id"])] & OFFER_STAGES) for r in values)})
    return result


def _timings(rows, histories):
    response_days, hr_days = [], []
    for row in rows:
        applied = _dt(row.get("applied_at"))
        if not applied: continue
        events = histories.get(int(row["id"]), [])
        responses = [_dt(e.get("changed_at")) for e in events if e.get("to_stage") in RESPONSE_STAGES]
        hrs = [_dt(e.get("changed_at")) for e in events if e.get("to_stage") == "HR_INTERVIEW"]
        if any(responses): response_days.append((min(v for v in responses if v) - applied).total_seconds() / 86400)
        if any(hrs): hr_days.append((min(v for v in hrs if v) - applied).total_seconds() / 86400)
    return {"time_to_first_response": _stats(response_days), "applied_to_hr_interview": _stats(hr_days)}


def _stats(values):
    if not values: return {"count": 0, "average": None, "median": None, "minimum": None, "maximum": None}
    return {"count": len(values), "average": mean(values), "median": median(values),
            "minimum": min(values), "maximum": max(values)}


def _rate(value, total): return round(value / total * 100, 1) if total else 0.0
def _dt(value): return parse_datetime(value) if value else None
