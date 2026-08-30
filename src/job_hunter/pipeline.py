from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path

from .config import load_profile
from .database import JobDatabase
from .discovery.aggregator import DiscoveryAggregator, DiscoveryResult
from .discovery.base import JobSource
from .models import Job
from .normalizer import normalize_job
from .scorer import score_job
from .discovery.target_registry import quality_score

REQUIRED_COLUMNS = {"title", "company", "location", "work_mode", "description", "source", "url"}


@dataclass(frozen=True, slots=True)
class PipelineResult:
    jobs: list[Job]
    inserted: int
    updated: int


@dataclass(frozen=True, slots=True)
class DiscoveryPipelineResult:
    jobs: list[Job]
    inserted: int
    updated: int
    discovery: DiscoveryResult


def run_pipeline(
    input_path: str | Path,
    profile_path: str | Path,
    database_path: str | Path,
) -> PipelineResult:
    jobs = _read_csv(input_path)
    return process_jobs(jobs, profile_path, database_path)


def run_discovery_pipeline(
    sources: list[JobSource],
    profile_path: str | Path,
    database_path: str | Path,
    queries: list[str] | None = None,
    location: str | None = None,
    limit: int | None = None,
    max_age_days: int | None = 14,
) -> DiscoveryPipelineResult:
    profile = load_profile(profile_path)
    database = JobDatabase(database_path)
    run_id = database.create_discovery_run([source.name for source in sources])
    try:
        discovery = DiscoveryAggregator(sources).discover(
            queries or _profile_aliases(profile), location=location, limit=limit,
            preferred_locations=[location] if location else profile.preferred_locations,
            max_age_days=max_age_days,
            priority_fresh_days=profile.priority_fresh_days,
        )
        processed = process_jobs(discovery.jobs, profile_path, database_path)
        counts = {decision: sum(job.decision == decision for job in processed.jobs) for decision in ("APPLY", "REVIEW", "REJECT")}
        database.finish_discovery_run(
            run_id, status="COMPLETED_WITH_ERRORS" if discovery.errors else "COMPLETED",
            preliminary=sum(stat.fetched for stat in discovery.stats.values()), new_jobs=processed.inserted,
            updated_jobs=processed.updated, duplicates=discovery.duplicates,
            apply_count=counts["APPLY"], review_count=counts["REVIEW"], reject_count=counts["REJECT"],
            errors=discovery.errors,
        )
        for source_name, stat in discovery.stats.items():
            source_jobs = [job for job in processed.jobs if job.source.casefold() == source_name.casefold()]
            if stat.sector == "Other" and source_jobs:
                sector_counts = {sector: sum(job.sector == sector for job in source_jobs)
                                 for sector in {job.sector for job in source_jobs}}
                stat.sector = max(sector_counts, key=sector_counts.get)
            stat.apply_count = sum(job.decision == "APPLY" for job in source_jobs)
            stat.review_count = sum(job.decision == "REVIEW" for job in source_jobs)
            stat.reject_count = sum(job.decision == "REJECT" for job in source_jobs)
            database.record_source_metric(
                run_id=run_id, source=source_name, target=stat.target, sector=stat.sector,
                fetched=stat.fetched, relevant_by_title=stat.relevant_by_title,
                relevant_after_description=stat.relevant_after_description,
                pre_score_rejected=stat.rejected_pre_score, scored=stat.scored,
                apply_count=stat.apply_count, review_count=stat.review_count, reject_count=stat.reject_count,
                duplicates=stat.duplicates, error=stat.error, latency_ms=stat.latency_ms,
                fresh_count=stat.fresh_count,
                quality_score=quality_score(stat.fetched, stat.relevant_after_description,
                                            stat.apply_count, stat.review_count, stat.duplicates,
                                            int(bool(stat.error)), stat.fresh_count),
            )
    except Exception as exc:
        database.finish_discovery_run(run_id, status="FAILED", errors={"pipeline": f"{type(exc).__name__}: {exc}"})
        raise
    return DiscoveryPipelineResult(
        jobs=rank_jobs(processed.jobs),
        inserted=processed.inserted,
        updated=processed.updated,
        discovery=discovery,
    )


def process_jobs(
    jobs: list[Job], profile_path: str | Path, database_path: str | Path
) -> PipelineResult:
    profile = load_profile(profile_path)
    database = JobDatabase(database_path)
    inserted = 0
    for job in jobs:
        inserted += int(process_job(job, profile, database))
    return PipelineResult(jobs=jobs, inserted=inserted, updated=len(jobs) - inserted)


def process_job(job: Job, profile, database: JobDatabase) -> bool:
    from .discovery.target_registry import detect_sector

    if not job.url:
        raise ValueError("Every job must have a URL for deduplication")
    normalize_job(job, profile.skills)
    detected_sector, detected_confidence = detect_sector(job.company, job.description, job.title)
    if detected_confidence > job.sector_confidence:
        job.sector, job.sector_confidence = detected_sector, detected_confidence
    result = score_job(job, profile)
    job.score, job.decision, job.reasons = result.score, result.decision, result.as_dict()
    from .application.detector import detect_application_channel
    detection = detect_application_channel(job.description, job.url, job.raw_data)
    job.application_method, job.application_email = detection.method.value, detection.email
    job.application_url, job.application_instructions = detection.application_url, detection.instructions
    job.email_subject = detection.required_subject
    return database.upsert(job)


def rank_jobs(jobs: list[Job]) -> list[Job]:
    priority = {"APPLY": 0, "REVIEW": 1, "REJECT": 2, None: 3}
    return sorted(
        jobs,
        key=lambda job: (
            priority.get(job.decision, 3), -(job.score or 0),
            -(job_published_timestamp(job)),
        ),
    )


def job_published_timestamp(job: Job) -> float:
    from .discovery.matching import parse_datetime
    parsed = parse_datetime(job.published_at)
    return parsed.timestamp() if parsed else 0.0


def _profile_aliases(profile) -> list[str]:
    from .semantics import expand_target_roles
    aliases = [alias for values in profile.query_groups.values() for alias in values]
    return list(dict.fromkeys([*(aliases or profile.search_queries), *expand_target_roles(profile.target_roles)]))


def _read_csv(path: str | Path) -> list[Job]:
    with Path(path).open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        missing = REQUIRED_COLUMNS - set(reader.fieldnames or [])
        if missing:
            raise ValueError(f"CSV is missing columns: {', '.join(sorted(missing))}")
        return [Job(**{column: row[column] for column in REQUIRED_COLUMNS}) for row in reader]
