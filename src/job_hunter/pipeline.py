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
        if not job.url:
            raise ValueError("Every job must have a URL for deduplication")
        normalize_job(job, profile.skills)
        result = score_job(job, profile)
        job.score = result.score
        job.decision = result.decision
        job.reasons = result.as_dict()
        inserted += int(database.upsert(job))
    return PipelineResult(jobs=jobs, inserted=inserted, updated=len(jobs) - inserted)


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
    aliases = [alias for values in profile.query_groups.values() for alias in values]
    return aliases or profile.search_queries


def _read_csv(path: str | Path) -> list[Job]:
    with Path(path).open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        missing = REQUIRED_COLUMNS - set(reader.fieldnames or [])
        if missing:
            raise ValueError(f"CSV is missing columns: {', '.join(sorted(missing))}")
        return [Job(**{column: row[column] for column in REQUIRED_COLUMNS}) for row in reader]
