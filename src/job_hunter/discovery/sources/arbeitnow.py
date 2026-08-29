from __future__ import annotations

from collections.abc import Callable
from typing import Any
from urllib.parse import urlencode

from ..base import JobSource, fetch_json
from ..models import RawJob
from .remoteok import _query_matches


class ArbeitnowSource(JobSource):
    name = "arbeitnow"
    endpoint = "https://www.arbeitnow.com/api/job-board-api"

    def __init__(self, fetcher: Callable[[str], Any] = fetch_json):
        self._fetcher = fetcher
        self._payload: Any = None

    def discover(self, query: str, location: str | None = None, limit: int | None = None) -> list[RawJob]:
        url = f"{self.endpoint}?{urlencode({'page': 1})}"
        if self._payload is None:
            self._payload = self._fetcher(url)
        payload = self._payload
        if not isinstance(payload, dict) or not isinstance(payload.get("data"), list):
            raise ValueError("Arbeitnow returned an unexpected response")
        jobs: list[RawJob] = []
        for item in payload["data"]:
            searchable = " ".join(
                [str(item.get("title", "")), str(item.get("description", "")), " ".join(item.get("tags") or [])]
            ).lower()
            if query and not _query_matches(query, searchable):
                continue
            item_location = str(item.get("location") or ("Remote" if item.get("remote") else ""))
            if location and location.lower() not in item_location.lower() and not (
                location.lower() == "remote" and item.get("remote")
            ):
                continue
            slug = str(item.get("slug") or "")
            job_url = str(item.get("url") or f"https://www.arbeitnow.com/view/{slug}")
            jobs.append(
                RawJob(
                    external_id=slug or job_url,
                    title=str(item.get("title") or ""),
                    company=str(item.get("company_name") or "Unknown"),
                    location=item_location,
                    work_mode="remote" if item.get("remote") else "onsite",
                    description=str(item.get("description") or ""),
                    source=self.name,
                    url=job_url,
                    published_at=str(item.get("created_at")) if item.get("created_at") else None,
                    raw_data=item,
                )
            )
            if limit is not None and len(jobs) >= limit:
                break
        return jobs
