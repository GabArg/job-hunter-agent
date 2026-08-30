from __future__ import annotations

from collections.abc import Callable
import json
import re
from typing import Any

from ..base import JobSource, fetch_json
from ..models import RawJob
from .remoteok import _query_matches


class GenericCareersSource(JobSource):
    """Adapter for a public JSON careers endpoint with conventional field names."""

    def __init__(
        self,
        name: str,
        endpoint: str,
        fetcher: Callable[[str], Any] = fetch_json,
        jobs_key: str = "jobs",
    ):
        if not endpoint.lower().startswith("https://"):
            raise ValueError("Generic careers endpoints must use HTTPS")
        self.name = name
        self.endpoint = endpoint
        self.jobs_key = jobs_key
        self._fetcher = fetcher
        self._payload: Any = None

    def discover(self, query: str, location: str | None = None, limit: int | None = None) -> list[RawJob]:
        if self._payload is None:
            self._payload = self._fetcher(self.endpoint)
        payload = self._payload
        items = payload.get(self.jobs_key) if isinstance(payload, dict) else payload
        if isinstance(payload, str):
            items = _json_ld_jobs(payload)
        if not isinstance(items, list):
            raise ValueError(f"{self.name} returned an unexpected response")
        results: list[RawJob] = []
        for item in items:
            title = str(item.get("title") or item.get("name") or "")
            description = str(item.get("description") or item.get("content") or "")
            item_location = _location(item.get("location"))
            if not title or not item.get("url") or not _query_matches(query, f"{title} {description}".lower()):
                continue
            if location and location.lower() not in item_location.lower():
                continue
            results.append(
                RawJob(
                    external_id=str(item.get("id") or item["url"]),
                    title=title,
                    company=str(item.get("company") or item.get("company_name") or self.name),
                    location=item_location,
                    work_mode=str(item.get("work_mode") or ("remote" if item.get("remote") else "")),
                    description=description,
                    source=self.name,
                    url=str(item["url"]),
                    published_at=str(item.get("published_at") or item.get("updated_at") or "") or None,
                    raw_data=item,
                )
            )
            if limit is not None and len(results) >= limit:
                break
        return results


def _location(value: Any) -> str:
    if isinstance(value, dict):
        return str(value.get("name") or value.get("location") or "")
    return str(value or "")


def _json_ld_jobs(document: str) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    scripts = re.findall(
        r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>', document,
        flags=re.IGNORECASE | re.DOTALL,
    )
    for script in scripts:
        try:
            value = json.loads(script)
        except json.JSONDecodeError:
            continue
        entries = value if isinstance(value, list) else value.get("@graph", [value])
        for entry in entries:
            entry_types = entry.get("@type", []) if isinstance(entry, dict) else []
            if isinstance(entry_types, str): entry_types = [entry_types]
            if not isinstance(entry, dict) or "JobPosting" not in entry_types:
                continue
            location = entry.get("jobLocation") or {}
            if isinstance(location, list): location = location[0] if location else {}
            address = location.get("address", {}) if isinstance(location, dict) else {}
            org = entry.get("hiringOrganization") or {}
            identifier = entry.get("identifier")
            if isinstance(identifier, dict): identifier = identifier.get("value") or identifier.get("name")
            results.append({
                "id": identifier,
                "title": entry.get("title"), "description": entry.get("description"),
                "company": org.get("name") if isinstance(org, dict) else org,
                "location": ", ".join(str(address.get(key)) for key in ("addressLocality", "addressRegion", "addressCountry") if address.get(key)),
                "work_mode": "remote" if entry.get("jobLocationType") == "TELECOMMUTE" else "onsite",
                "url": entry.get("url") or entry.get("sameAs"), "published_at": entry.get("datePosted"),
            })
    return results
