from __future__ import annotations

import html
import logging
import re
from dataclasses import dataclass, field
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from ..models import Job
from ..normalizer import clean_text
from .base import JobSource
from .matching import geography_compatible, is_fresh, title_matches
from .models import RawJob

logger = logging.getLogger(__name__)
TRACKING_PARAMETERS = {"utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content", "ref", "source"}


@dataclass(slots=True)
class SourceStats:
    fetched: int = 0
    relevant_by_title: int = 0
    rejected_pre_score: int = 0
    scored: int = 0
    duplicates: int = 0
    error: str | None = None

    @property
    def found(self) -> int: return self.fetched

    @property
    def accepted(self) -> int: return self.scored

    @property
    def filtered(self) -> int: return self.rejected_pre_score


@dataclass(slots=True)
class DiscoveryResult:
    jobs: list[Job] = field(default_factory=list)
    stats: dict[str, SourceStats] = field(default_factory=dict)

    @property
    def duplicates(self) -> int:
        return sum(stat.duplicates for stat in self.stats.values())

    @property
    def errors(self) -> dict[str, str]:
        return {name: stat.error for name, stat in self.stats.items() if stat.error}


class DiscoveryAggregator:
    def __init__(self, sources: list[JobSource]):
        self.sources = sources

    def discover(
        self,
        queries: str | list[str],
        location: str | None = None,
        limit: int | None = None,
        preferred_locations: list[str] | None = None,
        max_age_days: int | None = 14,
    ) -> DiscoveryResult:
        query_list = [queries] if isinstance(queries, str) else queries
        result = DiscoveryResult(stats={source.name: SourceStats() for source in self.sources})
        seen_urls: set[str] = set()
        seen_content: set[tuple[str, str, str]] = set()
        for source in self.sources:
            stat = result.stats[source.name]
            try:
                source_jobs: list[RawJob] = []
                for query in query_list:
                    remaining = None if limit is None else max(0, limit - len(source_jobs))
                    if remaining == 0:
                        break
                    source_jobs.extend(source.discover(query, location, remaining))
                stat.fetched = len(source_jobs)
                for raw in source_jobs:
                    if not title_matches(raw.title, query_list, raw.description):
                        stat.rejected_pre_score += 1
                        continue
                    stat.relevant_by_title += 1
                    geography_ok, _ = geography_compatible(raw, preferred_locations or [])
                    if not geography_ok or not is_fresh(raw.published_at, max_age_days):
                        stat.rejected_pre_score += 1
                        continue
                    job = raw_to_job(raw)
                    url_key = canonical_url(job.url)
                    content_key = (clean_text(job.company), clean_text(job.title), clean_text(job.location))
                    if (url_key and url_key in seen_urls) or content_key in seen_content:
                        stat.duplicates += 1
                        continue
                    if url_key:
                        seen_urls.add(url_key)
                    seen_content.add(content_key)
                    result.jobs.append(job)
                    stat.scored += 1
            except Exception as exc:  # A failed source must not stop discovery.
                logger.warning("Discovery source %s failed: %s", source.name, exc)
                stat.error = f"{type(exc).__name__}: {exc}"
        return result


def raw_to_job(raw: RawJob) -> Job:
    from .matching import normalize_datetime
    return Job(
        title=raw.title.strip(),
        company=raw.company.strip() or "Unknown",
        location=raw.location.strip(),
        work_mode=raw.work_mode.strip(),
        description=_plain_text(raw.description),
        source=raw.source.strip(),
        url=canonical_url(raw.url),
        published_at=normalize_datetime(raw.published_at) or raw.published_at,
        discovered_at=raw.discovered_at,
    )


def canonical_url(url: str) -> str:
    parts = urlsplit(url.strip())
    query = urlencode([(key, value) for key, value in parse_qsl(parts.query) if key.lower() not in TRACKING_PARAMETERS])
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), parts.path.rstrip("/"), query, ""))


def _plain_text(value: str) -> str:
    without_tags = re.sub(r"<[^>]+>", " ", value or "")
    return re.sub(r"\s+", " ", html.unescape(without_tags)).strip()
