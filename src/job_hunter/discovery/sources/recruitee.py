from __future__ import annotations

from collections.abc import Callable
from typing import Any
from urllib.parse import quote

from ..base import JobSource, fetch_json
from ..matching import title_matches
from ..models import RawJob


class RecruiteeSource(JobSource):
    """Public Recruitee careers feed; no authentication is used."""

    def __init__(self, company: str, account: str, fetcher: Callable[[str], Any] = fetch_json):
        self.company, self.account, self._fetcher = company, account, fetcher
        self.name, self._payload = f"recruitee:{company}", None

    def discover(self, query: str, location: str | None = None, limit: int | None = None) -> list[RawJob]:
        if self._payload is None:
            self._payload = self._fetcher(f"https://{quote(self.account)}.recruitee.com/api/offers/")
        items = self._payload.get("offers", []) if isinstance(self._payload, dict) else []
        results: list[RawJob] = []
        for item in items:
            title = str(item.get("title") or "")
            description = " ".join(str(item.get(key) or "") for key in ("description", "requirements"))
            if not title_matches(title, [query], description):
                continue
            locations = item.get("locations") or []
            location_text = "; ".join(_location(value) for value in locations) or _location(item.get("location"))
            results.append(RawJob(
                str(item.get("id") or item.get("slug") or ""), title, self.company, location_text,
                str(item.get("workplace") or item.get("remote") or ""), description, self.name,
                str(item.get("careers_url") or item.get("url") or f"https://{self.account}.recruitee.com/o/{item.get('slug', '')}"),
                str(item.get("published_at") or item.get("created_at") or "") or None, raw_data=item,
            ))
            if limit is not None and len(results) >= limit:
                break
        return results


def _location(value: Any) -> str:
    if isinstance(value, dict):
        return ", ".join(str(value.get(key)) for key in ("city", "state", "country") if value.get(key))
    return str(value or "")
