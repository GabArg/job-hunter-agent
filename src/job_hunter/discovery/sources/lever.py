from __future__ import annotations

from collections.abc import Callable
from typing import Any
from urllib.parse import quote

from ..base import JobSource, fetch_json
from ..matching import title_matches
from ..models import RawJob


class LeverSource(JobSource):
    def __init__(self, company: str, board_token: str, fetcher: Callable[[str], Any] = fetch_json, eu: bool = False):
        self.company, self.board_token, self._fetcher, self.eu = company, board_token, fetcher, eu
        self.name = f"lever:{company}"
        self._payload: Any = None

    def discover(self, query: str, location: str | None = None, limit: int | None = None) -> list[RawJob]:
        if self._payload is None:
            host = "api.eu.lever.co" if self.eu else "api.lever.co"
            self._payload = self._fetcher(f"https://{host}/v0/postings/{quote(self.board_token)}?mode=json")
        results = []
        for item in self._payload if isinstance(self._payload, list) else []:
            if not title_matches(str(item.get("text", "")), [query]): continue
            categories = item.get("categories") or {}
            results.append(RawJob(str(item.get("id", "")), str(item.get("text", "")), self.company,
                str(categories.get("location") or ""), str(item.get("workplaceType") or ""),
                str(item.get("descriptionPlain") or item.get("description") or ""), self.name,
                str(item.get("hostedUrl") or ""), str(item.get("createdAt") or "") or None, raw_data=item))
            if limit is not None and len(results) >= limit: break
        return results
