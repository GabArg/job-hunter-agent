from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from .cv import HTMLCVRenderer, adapt_cv, load_master_cv
from .database import JobDatabase


def generate_job_cv(database_path: str | Path, job_id: int, master_path: str | Path = "private/master_cv.yaml",
                    output_root: str | Path = "outputs/cvs", allow_reject: bool = False) -> tuple[Path, object]:
    database = JobDatabase(database_path); job = database.get_job(job_id=job_id)
    if job is None: raise KeyError(f"Job not found: {job_id}")
    adapted = adapt_cv(job, load_master_cv(master_path), allow_reject=allow_reject)
    output = HTMLCVRenderer().render_to_file(adapted, Path(output_root) / str(job_id) / "cv.html")
    database.set_application_status(job_id, "CV_GENERATED")
    return output, adapted


def next_schedule_time(times: list[str], now: datetime | None = None) -> datetime | None:
    if not times: return None
    current = now or datetime.now().astimezone()
    candidates = []
    for offset in (0, 1):
        day = (current + timedelta(days=offset)).date()
        for value in times:
            hour, minute = (int(part) for part in value.split(":"))
            candidate = datetime.combine(day, datetime.min.time(), tzinfo=current.tzinfo).replace(hour=hour, minute=minute)
            if candidate > current: candidates.append(candidate)
    return min(candidates) if candidates else None
