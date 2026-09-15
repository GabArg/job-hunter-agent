from __future__ import annotations

from collections.abc import Callable
from typing import Any
from urllib.parse import quote

from ..base import JobSource, fetch_json
from ..matching import title_matches
from ..models import RawJob


class WorkableSource(JobSource):
    def __init__(self, company: str, board_token: str, fetcher: Callable[[str], Any] = fetch_json):
        self.company, self.board_token, self._fetcher = company, board_token, fetcher
        self.name, self._payload = f"workable:{company}", None

    def discover(self, query: str | list[str], location: str | None = None, limit: int | None = None) -> list[RawJob]:
        if self._payload is None:
            self._payload = self._fetcher(
                f"https://www.workable.com/api/accounts/{quote(self.board_token)}?details=false")
        items = self._payload.get("jobs", []) if isinstance(self._payload, dict) else []
        results = []
        for item in items:
            if not title_matches(str(item.get("title", "")), [query] if isinstance(query, str) else query): continue
            loc = item.get("location") or {}
            location_text = loc.get("location_str") if isinstance(loc, dict) else loc
            if not location_text:
                locations = item.get("locations") or []
                location_text = "; ".join(
                    ", ".join(str(value.get(key)) for key in ("city", "state", "country") if value.get(key))
                    for value in locations if isinstance(value, dict))
            description = str(item.get("description") or item.get("description_plain") or " ".join(
                str(item.get(key) or "") for key in ("function", "department", "industry", "experience")))
            results.append(RawJob(str(item.get("id") or item.get("shortcode") or ""),
                str(item.get("title", "")), self.company, str(location_text or ""),
                (str(loc.get("workplace_type") or "") if isinstance(loc, dict) else "") or
                ("remote" if item.get("telecommuting") else ""), description, self.name,
                str(item.get("url") or item.get("shortlink") or ""),
                str(item.get("created_at") or "") or None, raw_data=item))
            if limit is not None and len(results) >= limit: break
        return results
