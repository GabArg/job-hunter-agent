from __future__ import annotations

import json
import time
from abc import ABC, abstractmethod
from typing import Any
import requests

from .models import RawJob

USER_AGENT = "JobHunterAgent/0.2 (+local discovery; respectful public API client)"


class JobSource(ABC):
    """Contract implemented by every discovery source."""

    name: str

    @abstractmethod
    def discover(
        self, query: str | list[str], location: str | None = None, limit: int | None = None
    ) -> list[RawJob]:
        """Return public job listings matching the requested search."""


HTTP_CONNECT_TIMEOUT_SECONDS = 5.0
HTTP_READ_TIMEOUT_SECONDS = 12.0
HTTP_TIMEOUT = (HTTP_CONNECT_TIMEOUT_SECONDS, HTTP_READ_TIMEOUT_SECONDS)
HTTP_TOTAL_TIMEOUT_SECONDS = 20.0
TRANSIENT_HTTP_STATUSES = {429, 502, 503, 504}


def fetch_json(url: str, timeout: tuple[float, float] | float = HTTP_TIMEOUT, max_retries: int = 1) -> Any:
    for attempt in range(max_retries + 1):
        try:
            response = requests.get(url, headers={"Accept": "application/json", "User-Agent": USER_AGENT},
                                    timeout=timeout, stream=True)
            response.raise_for_status()
            return json.loads(_read_bounded(response, HTTP_TOTAL_TIMEOUT_SECONDS))
        except requests.HTTPError as exc:
            status = exc.response.status_code if exc.response is not None else None
            if status not in TRANSIENT_HTTP_STATUSES or attempt >= max_retries:
                raise
            time.sleep(0.25)
        except (requests.ConnectionError, requests.Timeout):
            raise


def fetch_text(url: str, timeout: tuple[float, float] | float = HTTP_TIMEOUT) -> str:
    response = requests.get(url, headers={"Accept": "text/html,application/xhtml+xml", "User-Agent": USER_AGENT},
                            timeout=timeout, stream=True)
    response.raise_for_status()
    encoding = response.encoding or "utf-8"
    return _read_bounded(response, HTTP_TOTAL_TIMEOUT_SECONDS).decode(encoding, errors="replace")


def _read_bounded(response: requests.Response, total_timeout: float) -> bytes:
    started = time.monotonic(); chunks: list[bytes] = []
    for chunk in response.iter_content(chunk_size=64 * 1024):
        if time.monotonic() - started > total_timeout:
            response.close()
            raise TimeoutError(f"response body exceeded {total_timeout:g}s total timeout")
        if chunk: chunks.append(chunk)
    return b"".join(chunks)
