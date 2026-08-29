from __future__ import annotations

from collections.abc import Callable
from typing import Any
from urllib.parse import quote

from ..base import JobSource, fetch_json
from ..matching import title_matches
from ..models import RawJob


class GreenhouseSource(JobSource):
    def __init__(self, company: str, board_token: str, fetcher: Callable[[str], Any] = fetch_json):
        self.company, self.board_token, self._fetcher = company, board_token, fetcher
        self.name = f"greenhouse:{company}"
        self._payload: Any = None

    def discover(self, query: str, location: str | None = None, limit: int | None = None) -> list[RawJob]:
        if self._payload is None:
            url = f"https://boards-api.greenhouse.io/v1/boards/{quote(self.board_token)}/jobs?content=true"
            self._payload = self._fetcher(url)
        items = self._payload.get("jobs", []) if isinstance(self._payload, dict) else []
        results = []
        for item in items:
            item_location = str((item.get("location") or {}).get("name") or "")
            if not title_matches(str(item.get("title", "")), [query]):
                continue
            results.append(RawJob(str(item.get("id", "")), str(item.get("title", "")), self.company,
                item_location, _mode(item_location), str(item.get("content") or ""), self.name,
                str(item.get("absolute_url") or ""), str(item.get("updated_at") or "") or None, raw_data=item))
            if limit is not None and len(results) >= limit: break
        return results


def _mode(location: str) -> str:
    text = location.lower()
    return "remote" if "remote" in text else "hybrid" if "hybrid" in text else "onsite"
