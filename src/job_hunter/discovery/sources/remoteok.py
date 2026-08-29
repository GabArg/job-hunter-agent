from __future__ import annotations

from collections.abc import Callable
from typing import Any

from ..base import JobSource, fetch_json
from ..models import RawJob


class RemoteOKSource(JobSource):
    name = "remoteok"
    endpoint = "https://remoteok.com/api"

    def __init__(self, fetcher: Callable[[str], Any] = fetch_json):
        self._fetcher = fetcher
        self._payload: Any = None

    def discover(self, query: str, location: str | None = None, limit: int | None = None) -> list[RawJob]:
        if self._payload is None:
            self._payload = self._fetcher(self.endpoint)
        payload = self._payload
        if not isinstance(payload, list):
            raise ValueError("Remote OK returned an unexpected response")
        jobs: list[RawJob] = []
        for item in payload:
            if not isinstance(item, dict) or not item.get("position") or not item.get("url"):
                continue  # The first feed item is normally a legal notice.
            searchable = " ".join(
                [str(item.get("position", "")), str(item.get("description", "")), " ".join(item.get("tags") or [])]
            ).lower()
            if query and not _query_matches(query, searchable):
                continue
            item_location = str(item.get("location") or "Remote")
            if location and location.lower() not in item_location.lower() and location.lower() != "remote":
                continue
            jobs.append(
                RawJob(
                    external_id=str(item.get("id") or item.get("slug") or item["url"]),
                    title=str(item["position"]),
                    company=str(item.get("company") or "Unknown"),
                    location=item_location,
                    work_mode="remote",
                    description=str(item.get("description") or ""),
                    source=self.name,
                    url=str(item["url"]),
                    published_at=str(item.get("date")) if item.get("date") else None,
                    raw_data=item,
                )
            )
            if limit is not None and len(jobs) >= limit:
                break
        return jobs


def _query_matches(query: str, text: str) -> bool:
    words = [word for word in query.lower().split() if len(word) > 1]
    return all(word in text for word in words)
