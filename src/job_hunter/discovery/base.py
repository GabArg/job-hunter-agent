from __future__ import annotations

import json
import time
from abc import ABC, abstractmethod
from typing import Any
from urllib.request import Request, urlopen

from .models import RawJob

USER_AGENT = "JobHunterAgent/0.2 (+local discovery; respectful public API client)"


class JobSource(ABC):
    """Contract implemented by every discovery source."""

    name: str

    @abstractmethod
    def discover(
        self, query: str, location: str | None = None, limit: int | None = None
    ) -> list[RawJob]:
        """Return public job listings matching the requested search."""


def fetch_json(url: str, timeout: float = 15.0, max_retries: int = 1) -> Any:
    request = Request(url, headers={"Accept": "application/json", "User-Agent": USER_AGENT})
    for attempt in range(max_retries + 1):
        try:
            with urlopen(request, timeout=timeout) as response:  # noqa: S310 - URLs are adapter-owned
                return json.load(response)
        except Exception:
            if attempt >= max_retries:
                raise
            time.sleep(0.25)


def fetch_text(url: str, timeout: float = 15.0) -> str:
    request = Request(url, headers={"Accept": "text/html,application/xhtml+xml", "User-Agent": USER_AGENT})
    with urlopen(request, timeout=timeout) as response:  # noqa: S310 - target is user-configured HTTPS
        return response.read().decode(response.headers.get_content_charset() or "utf-8", errors="replace")
