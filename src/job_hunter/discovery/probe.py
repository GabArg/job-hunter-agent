from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlsplit

from .base import fetch_json, fetch_text
from .sources.generic_careers import _json_ld_jobs
from .target_registry import CompanyTarget


@dataclass(slots=True)
class ProbeResult:
    company: str
    detected_source_type: str = "unknown"
    endpoint: str = ""
    token: str = ""
    reachable: bool = False
    jobs_found: int = 0
    sample_titles: list[str] = field(default_factory=list)
    coverage_tags: list[str] = field(default_factory=list)
    status: str = "UNKNOWN"
    error: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def probe_target(value: str | CompanyTarget) -> ProbeResult:
    if isinstance(value, CompanyTarget):
        company, source_type, token, url = value.company, value.source_type, value.token, value.url
        if source_type not in {"greenhouse", "lever", "ashby", "workable", "smartrecruiters", "recruitee", "generic"} and url:
            source_type, token = detect_target(url)
    else:
        url = value.strip(); source_type, token = detect_target(url)
        company = token or _company_from_url(url)
    if source_type == "unknown":
        return ProbeResult(company=company or str(value), endpoint=url, status="UNKNOWN")
    endpoint = endpoint_for(source_type, token, url)
    result = ProbeResult(company=company, detected_source_type=source_type, endpoint=endpoint, token=token)
    try:
        payload = fetch_text(endpoint) if source_type == "generic" else fetch_json(endpoint)
        titles = extract_titles(source_type, payload)
        result.reachable = True
        result.jobs_found = len(titles)
        result.sample_titles = titles[:5]
        result.coverage_tags = coverage_tags(titles)
        result.status = "HEALTHY"
    except Exception as exc:
        result.status = "BROKEN"
        result.error = f"{type(exc).__name__}: {exc}"
    return result


def detect_target(url: str) -> tuple[str, str]:
    if not url.lower().startswith("https://"):
        return "unknown", ""
    parts = urlsplit(url); host = parts.netloc.casefold(); path = [part for part in parts.path.split("/") if part]
    if "greenhouse.io" in host:
        marker = next((i for i, part in enumerate(path) if part in {"boards", "embed"}), -1)
        return "greenhouse", path[marker + 1] if marker >= 0 and len(path) > marker + 1 else (path[0] if path else "")
    if "lever.co" in host: return "lever", path[0] if path else ""
    if "ashbyhq.com" in host: return "ashby", path[-1] if "posting-api" in path else (path[0] if path else "")
    if "workable.com" in host: return "workable", path[0] if path else ""
    if "smartrecruiters.com" in host:
        marker = path.index("companies") if "companies" in path else -1
        return "smartrecruiters", path[marker + 1] if marker >= 0 and len(path) > marker + 1 else (path[0] if path else "")
    if host.endswith(".recruitee.com"): return "recruitee", host.split(".")[0]
    return "generic", ""


def endpoint_for(source_type: str, token: str, url: str = "") -> str:
    encoded = quote(token)
    return {
        "greenhouse": f"https://boards-api.greenhouse.io/v1/boards/{encoded}/jobs?content=true",
        "lever": f"https://api.lever.co/v0/postings/{encoded}?mode=json",
        "ashby": f"https://api.ashbyhq.com/posting-api/job-board/{encoded}?includeCompensation=true",
        "workable": f"https://www.workable.com/api/accounts/{encoded}?details=true",
        "smartrecruiters": f"https://api.smartrecruiters.com/v1/companies/{encoded}/postings?limit=100",
        "recruitee": f"https://{encoded}.recruitee.com/api/offers/",
        "generic": url,
    }[source_type]


def extract_titles(source_type: str, payload: Any) -> list[str]:
    if source_type == "lever": items = payload if isinstance(payload, list) else []
    elif source_type == "smartrecruiters": items = payload.get("content", []) if isinstance(payload, dict) else []
    elif source_type == "recruitee": items = payload.get("offers", []) if isinstance(payload, dict) else []
    elif source_type == "generic": items = _json_ld_jobs(payload) if isinstance(payload, str) else []
    else: items = payload.get("jobs", []) if isinstance(payload, dict) else []
    key = "text" if source_type == "lever" else "name" if source_type == "smartrecruiters" else "title"
    return [str(item.get(key)) for item in items if isinstance(item, dict) and item.get(key)]


def coverage_tags(titles: list[str]) -> list[str]:
    rules = {
        "data": ("data", "datos", "analytics"), "bi": ("business intelligence", " bi "),
        "business": ("business", "analista de negocio", "functional analyst"),
        "operations": ("operations", "operaciones", "process", "procesos"),
        "pricing": ("pricing", "precios", "margin"), "commercial": ("commercial", "comercial"),
        "reporting": ("reporting", "reportes"), "performance": ("performance",),
        "revenue": ("revenue",), "customer-analytics": ("customer analytics", "customer insights"),
    }
    text = f" {' '.join(titles).casefold()} "
    return [tag for tag, signals in rules.items() if any(signal in text for signal in signals)]


def write_probe_report(results: list[ProbeResult], directory: str | Path = "data/reports") -> Path:
    import json
    path = Path(directory); path.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    output = path / f"source_probe_{timestamp}.json"
    output.write_text(json.dumps([result.as_dict() for result in results], ensure_ascii=False, indent=2), encoding="utf-8")
    return output


def _company_from_url(url: str) -> str:
    host = urlsplit(url).netloc
    return host.split(".")[0] if host else url
