from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path

from .config import load_profile
from .database import JobDatabase
from .models import Job
from .normalizer import normalize_job
from .scorer import score_job

REQUIRED_COLUMNS = {"title", "company", "location", "work_mode", "description", "source", "url"}


@dataclass(frozen=True, slots=True)
class PipelineResult:
    jobs: list[Job]
    inserted: int
    updated: int


def run_pipeline(
    input_path: str | Path,
    profile_path: str | Path,
    database_path: str | Path,
) -> PipelineResult:
    profile = load_profile(profile_path)
    database = JobDatabase(database_path)
    jobs = _read_csv(input_path)
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


def _read_csv(path: str | Path) -> list[Job]:
    with Path(path).open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        missing = REQUIRED_COLUMNS - set(reader.fieldnames or [])
        if missing:
            raise ValueError(f"CSV is missing columns: {', '.join(sorted(missing))}")
        return [Job(**{column: row[column] for column in REQUIRED_COLUMNS}) for row in reader]
