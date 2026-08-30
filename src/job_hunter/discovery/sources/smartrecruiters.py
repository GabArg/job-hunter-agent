from __future__ import annotations

from collections.abc import Callable
from typing import Any
from urllib.parse import quote

from ..base import JobSource, fetch_json
from ..matching import title_matches
from ..models import RawJob
from ...normalizer import normalize_work_mode


class SmartRecruitersSource(JobSource):
    """Adapter for the documented public SmartRecruiters postings feed."""

    def __init__(self, company: str, account: str, fetcher: Callable[[str], Any] = fetch_json):
        self.company, self.account, self._fetcher = company, account, fetcher
        self.name, self._payload = f"smartrecruiters:{company}", None
        self._details: dict[str, dict[str, Any]] = {}

    def discover(self, query: str, location: str | None = None, limit: int | None = None) -> list[RawJob]:
        if self._payload is None:
            self._payload = self._fetcher(f"https://api.smartrecruiters.com/v1/companies/{quote(self.account)}/postings?limit=100")
        items = self._payload.get("content", []) if isinstance(self._payload, dict) else []
        results: list[RawJob] = []
        for item in items:
            title = str(item.get("name") or "")
            if not title_matches(title, [query]):
                continue
            job_id = str(item.get("id") or "")
            if job_id not in self._details:
                detail = self._fetcher(f"https://api.smartrecruiters.com/v1/companies/{quote(self.account)}/postings/{quote(job_id)}")
                self._details[job_id] = detail if isinstance(detail, dict) else {}
            detail = self._details[job_id]
            loc = item.get("location") or {}
            location_text = ", ".join(str(loc.get(key)) for key in ("city", "region", "country") if loc.get(key))
            sections = ((detail.get("jobAd") or {}).get("sections") or {})
            description = " ".join(str(section.get("text") or "") for section in sections.values() if isinstance(section, dict))
            results.append(RawJob(
                job_id, title, self.company, location_text, normalize_work_mode(None, description, detail),
                description, self.name, str(detail.get("postingUrl") or detail.get("applyUrl") or item.get("ref") or f"https://jobs.smartrecruiters.com/{self.account}/{job_id}"),
                str(item.get("releasedDate") or "") or None, raw_data=item,
            ))
            if limit is not None and len(results) >= limit:
                break
        return results
