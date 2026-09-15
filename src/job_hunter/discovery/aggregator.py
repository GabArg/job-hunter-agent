from __future__ import annotations

import html
import logging
import re
import hashlib
from concurrent.futures import ThreadPoolExecutor, as_completed
from time import perf_counter
from dataclasses import dataclass, field
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from ..models import Job
from ..normalizer import clean_text
from .base import JobSource
from .matching import description_relevant, geography_compatible, is_fresh, is_priority_fresh, title_matches
from .target_registry import detect_sector
from .models import RawJob

logger = logging.getLogger(__name__)
TRACKING_PARAMETERS = {"utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content", "ref", "source"}


@dataclass(slots=True)
class SourceStats:
    fetched: int = 0
    relevant_by_title: int = 0
    relevant_after_description: int = 0
    rejected_pre_score: int = 0
    scored: int = 0
    duplicates: int = 0
    error: str | None = None
    latency_ms: int = 0
    timed_out: bool = False
    priority_tier: str = "TIER_2"
    value_score: float = 30.0
    cooldown_until: str | None = None
    skipped_reason: str | None = None
    target: str | None = None
    sector: str = "Other"
    apply_count: int = 0
    review_count: int = 0
    reject_count: int = 0
    fresh_count: int = 0
    fresh: int = 0
    geo_eligible: int = 0
    role_relevant: int = 0
    deduped: int = 0
    new_jobs: int = 0
    updated_jobs: int = 0
    filter_reasons: dict[str, int] = field(default_factory=lambda: {
        "stale": 0, "geo_incompatible": 0, "role_irrelevant": 0,
        "duplicate": 0, "parse_error": 0, "source_error": 0,
    })

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
    total_elapsed_ms: int = 0
    sources_started: int = 0
    sources_completed: int = 0
    sources_failed: int = 0
    sources_timed_out: int = 0
    sources_skipped_budget: int = 0
    sources_cooldown: int = 0
    sources_exploration_skipped: int = 0
    quality_guard: str = "NOT_EVALUATED"

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
        priority_fresh_days: int = 3,
        max_workers: int = 6,
        target_timeout_seconds: float = 45.0,
        run_budget_seconds: float | None = 120.0,
    ) -> DiscoveryResult:
        query_list = [queries] if isinstance(queries, str) else queries
        started_all = perf_counter()
        ordered_sources = sorted(self.sources, key=lambda source: (source.name.casefold(), getattr(source, "target_id", "")))
        result = DiscoveryResult(stats={source.name: SourceStats() for source in ordered_sources})
        collected: dict[str, list[RawJob]] = {}
        workers = max(1, min(int(max_workers), len(ordered_sources) or 1))
        deadline = started_all + run_budget_seconds if run_budget_seconds is not None else None
        runnable: dict[str, list[JobSource]] = {tier: [] for tier in ("TIER_1", "TIER_2", "TIER_3")}
        for source in ordered_sources:
            stat = result.stats[source.name]
            stat.target = getattr(source, "target_id", source.name); stat.sector = getattr(source, "sector", "Other")
            stat.priority_tier = getattr(source, "priority_tier", "TIER_2")
            stat.value_score = float(getattr(source, "source_value_score", 30.0))
            stat.cooldown_until = getattr(source, "cooldown_until", None)
            stat.skipped_reason = getattr(source, "skip_reason", None)
            if stat.skipped_reason:
                collected[source.name] = []
                result.sources_cooldown += int(stat.skipped_reason == "COOLDOWN")
                result.sources_exploration_skipped += int(stat.skipped_reason == "EXPLORATION_NOT_DUE")
            else:
                runnable[stat.priority_tier].append(source)
        for tier in ("TIER_1", "TIER_2", "TIER_3"):
            tier_sources = sorted(runnable[tier], key=lambda source: (
                -float(getattr(source, "source_value_score", 30)), source.name.casefold()))
            for offset in range(0, len(tier_sources), workers):
                batch = tier_sources[offset:offset + workers]
                if deadline is not None and perf_counter() >= deadline:
                    for source in tier_sources[offset:]:
                        result.stats[source.name].skipped_reason = "SKIPPED_BUDGET"; collected[source.name] = []
                        result.sources_skipped_budget += 1
                    break
                result.sources_started += len(batch)
                with ThreadPoolExecutor(max_workers=len(batch), thread_name_prefix="discovery") as executor:
                    futures = {executor.submit(_collect_source, source, query_list, location, limit): source for source in batch}
                    for future in as_completed(futures):
                        source = futures[future]; stat = result.stats[source.name]
                        try:
                            source_jobs, stat.latency_ms = future.result()
                            collected[source.name] = source_jobs
                            if stat.latency_ms > target_timeout_seconds * 1000:
                                stat.timed_out = True
                                stat.error = f"TargetTimeout: elapsed {stat.latency_ms}ms exceeded {target_timeout_seconds:g}s"
                                stat.filter_reasons["source_error"] += 1
                        except Exception as exc:
                            logger.warning("Discovery source %s failed: %s", source.name, exc)
                            stat.error = f"{type(exc).__name__}: {exc}"
                            stat.timed_out = isinstance(exc, TimeoutError) or "timed out" in str(exc).casefold()
                            stat.filter_reasons["source_error"] += 1
                            collected[source.name] = []
                        result.sources_completed += 1
        result.sources_failed = sum(bool(stat.error) for stat in result.stats.values())
        result.sources_timed_out = sum(stat.timed_out for stat in result.stats.values())
        seen_urls: set[str] = set()
        seen_fingerprints: set[str] = set()
        for source in ordered_sources:
            stat = result.stats[source.name]
            try:
                source_jobs = sorted(collected[source.name], key=lambda raw: (
                    raw.source.casefold(), stat.target or "", raw.title.casefold(), canonical_url(raw.url)))
                stat.fetched = len(source_jobs)
                for raw in source_jobs:
                    if not raw.title.strip() or not raw.url.strip():
                        stat.filter_reasons["parse_error"] += 1
                        stat.rejected_pre_score += 1
                        continue
                    if not is_fresh(raw.published_at, max_age_days):
                        stat.filter_reasons["stale"] += 1
                        stat.rejected_pre_score += 1
                        continue
                    stat.fresh += 1
                    geography_ok, _ = geography_compatible(raw, preferred_locations or [])
                    if not geography_ok:
                        stat.filter_reasons["geo_incompatible"] += 1
                        stat.rejected_pre_score += 1
                        continue
                    stat.geo_eligible += 1
                    if not title_matches(raw.title, query_list, raw.description):
                        stat.filter_reasons["role_irrelevant"] += 1
                        stat.rejected_pre_score += 1
                        continue
                    stat.relevant_by_title += 1
                    if not description_relevant(raw.title, raw.description):
                        stat.filter_reasons["role_irrelevant"] += 1
                        stat.rejected_pre_score += 1
                        continue
                    stat.relevant_after_description += 1
                    stat.role_relevant += 1
                    job = raw_to_job(raw)
                    configured_sector = getattr(source, "sector", "Other")
                    if configured_sector and configured_sector != "Other":
                        job.sector, job.sector_confidence = configured_sector, float(getattr(source, "sector_confidence", 1.0))
                    else:
                        job.sector, job.sector_confidence = detect_sector(job.company, job.description, job.title)
                    job.priority_fresh = is_priority_fresh(job.published_at, priority_fresh_days)
                    url_key = canonical_url(job.url)
                    fingerprint = job_fingerprint(job)
                    if (url_key and url_key in seen_urls) or fingerprint in seen_fingerprints:
                        stat.duplicates += 1
                        stat.filter_reasons["duplicate"] += 1
                        continue
                    if url_key:
                        seen_urls.add(url_key)
                    seen_fingerprints.add(fingerprint)
                    result.jobs.append(job)
                    stat.deduped += 1
                    stat.scored += 1
                    stat.fresh_count += int(job.priority_fresh)
            except Exception as exc:
                logger.warning("Discovery source %s failed: %s", source.name, exc)
                stat.error = f"{type(exc).__name__}: {exc}"
                stat.filter_reasons["source_error"] += 1
        result.total_elapsed_ms = round((perf_counter() - started_all) * 1000)
        return result


def _collect_source(source: JobSource, queries: list[str], location: str | None,
                    limit: int | None) -> tuple[list[RawJob], int]:
    started = perf_counter()
    jobs = source.discover(queries, location, limit)
    return _round_robin_unique([jobs], limit), round((perf_counter() - started) * 1000)


def _round_robin_unique(batches: list[list[RawJob]], limit: int | None) -> list[RawJob]:
    """Avoid early-query starvation while counting each source posting once."""
    result: list[RawJob] = []
    seen: set[str] = set()
    width = max((len(batch) for batch in batches), default=0)
    for index in range(width):
        for batch in batches:
            if index >= len(batch):
                continue
            raw = batch[index]
            key = canonical_url(raw.url) or f"{raw.source}:{raw.external_id}"
            if key in seen:
                continue
            seen.add(key); result.append(raw)
            if limit is not None and len(result) >= limit:
                return result
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
        raw_data=raw.raw_data,
    )


def canonical_url(url: str) -> str:
    parts = urlsplit(url.strip())
    query = urlencode([(key, value) for key, value in parse_qsl(parts.query) if key.lower() not in TRACKING_PARAMETERS])
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), parts.path.rstrip("/"), query, ""))


def job_fingerprint(job: Job) -> str:
    # The description prevents false merges for distinct openings sharing title/location.
    value = "|".join(clean_text(part) for part in (job.company, job.title, job.location, job.description))
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _plain_text(value: str) -> str:
    without_tags = re.sub(r"<[^>]+>", " ", value or "")
    return re.sub(r"\s+", " ", html.unescape(without_tags)).strip()
