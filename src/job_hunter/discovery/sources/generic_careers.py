from __future__ import annotations

from collections.abc import Callable
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
