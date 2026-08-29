from __future__ import annotations

from collections.abc import Callable
from typing import Any
from urllib.parse import quote

from ..base import JobSource, fetch_json
from ..matching import title_matches
from ..models import RawJob


class AshbySource(JobSource):
    def __init__(self, company: str, board_token: str, fetcher: Callable[[str], Any] = fetch_json):
        self.company, self.board_token, self._fetcher = company, board_token, fetcher
        self.name, self._payload = f"ashby:{company}", None

    def discover(self, query: str, location: str | None = None, limit: int | None = None) -> list[RawJob]:
        if self._payload is None:
            self._payload = self._fetcher(
                f"https://api.ashbyhq.com/posting-api/job-board/{quote(self.board_token)}?includeCompensation=true")
        results = []
        for item in self._payload.get("jobs", []) if isinstance(self._payload, dict) else []:
            if not item.get("isListed", True) or not title_matches(str(item.get("title", "")), [query]): continue
            results.append(RawJob(str(item.get("id") or item.get("jobUrl") or ""), str(item.get("title", "")),
                self.company, str(item.get("location") or ""), "remote" if item.get("isRemote") else "onsite",
                str(item.get("descriptionPlain") or item.get("descriptionHtml") or ""), self.name,
                str(item.get("jobUrl") or item.get("applyUrl") or ""),
                str(item.get("publishedAt") or "") or None, raw_data=item))
            if limit is not None and len(results) >= limit: break
        return results
