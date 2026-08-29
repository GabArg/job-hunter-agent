from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class RawJob:
    external_id: str
    title: str
    company: str
    location: str
    work_mode: str
    description: str
    source: str
    url: str
    published_at: str | None = None
    raw_data: dict[str, Any] | None = field(default=None, repr=False)
