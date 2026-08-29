from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from .config import load_profile
from .discovery.factory import build_sources
from .pipeline import run_discovery_pipeline, run_pipeline
from .cv import HTMLCVRenderer, adapt_cv, load_master_cv
from .database import JobDatabase


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Score and persist job offers")
    subparsers = parser.add_subparsers(dest="command", required=True)
    run = subparsers.add_parser("run", help="Run the CSV pipeline")
    run.add_argument("--input", required=True, help="Input CSV path")
    run.add_argument("--profile", default="config/profile.yaml", help="YAML profile path")
    run.add_argument("--database", default="data/jobs.db", help="SQLite database path")
    discover = subparsers.add_parser("discover", help="Discover, score and persist public jobs")
    discover.add_argument("--query", action="append", help="Query; may be supplied more than once")
    discover.add_argument("--query-group", action="append", help="Configured query group; may be repeated")
    discover.add_argument("--location", help="Optional location filter")
    discover.add_argument("--limit", type=int, default=10, help="Maximum matches per source")
    discover.add_argument("--max-age-days", type=int, default=14, help="Maximum posting age (default: 14)")
    discover.add_argument(
        "--source", action="append",
        choices=("remoteok", "arbeitnow", "greenhouse", "lever", "ashby", "workable", "generic"),
        help="Source; may be supplied more than once (default: all)",
    )
    discover.add_argument("--profile", default="config/profile.yaml", help="YAML profile path")
    discover.add_argument("--database", default="data/jobs.db", help="SQLite database path")
    cv = subparsers.add_parser("cv", help="Generate a factually validated tailored CV")
    target = cv.add_mutually_exclusive_group(required=True)
    target.add_argument("--job-id", type=int, help="Stored job ID")
    target.add_argument("--url", help="Stored job URL")
    cv.add_argument("--master-cv", default="private/master_cv.yaml", help="Private factual master CV")
    cv.add_argument("--output", default="outputs", help="Output directory")
    cv.add_argument("--database", default="data/jobs.db", help="SQLite database path")
    cv.add_argument("--allow-reject", action="store_true", help="Explicitly allow CV for a REJECT job")
    return parser


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    args = build_parser().parse_args()
    if args.command == "run":
        result = run_pipeline(args.input, args.profile, args.database)
        print(f"Processed {len(result.jobs)} jobs ({result.inserted} inserted, {result.updated} updated)")
    elif args.command == "discover":
        profile = load_profile(args.profile)
        queries = list(args.query or [])
        for group in args.query_group or []:
            try:
                queries.extend(profile.query_groups[group.lower()])
            except KeyError as exc:
                raise SystemExit(f"Unknown query group: {group}") from exc
        result = run_discovery_pipeline(
            build_sources(profile, args.source), args.profile, args.database,
            queries=queries or None, location=args.location, limit=args.limit,
            max_age_days=args.max_age_days,
        )
        print(f"Discovered {len(result.jobs)} jobs ({result.inserted} new, {result.updated} existing)")
        for name, stat in result.discovery.stats.items():
            status = f"ERROR {stat.error}" if stat.error else "OK"
            print(
                f"{name}: fetched={stat.fetched} title_relevant={stat.relevant_by_title} "
                f"pre_score_rejected={stat.rejected_pre_score} scored={stat.scored} "
                f"duplicates={stat.duplicates} status={status}"
            )
    else:
        job = JobDatabase(args.database).get_job(args.job_id, args.url)
        if job is None:
            raise SystemExit("Job not found in SQLite")
        adapted = adapt_cv(job, load_master_cv(args.master_cv), allow_reject=args.allow_reject)
        safe_name = "".join(character if character.isalnum() else "-" for character in job.title).strip("-").lower()
        output = HTMLCVRenderer().render_to_file(adapted, Path(args.output) / f"cv-{job.id}-{safe_name}.html")
        print(f"CV {adapted.validation_status} | {adapted.approval_state} | {output}")
        return
    for job in result.jobs[:20]:
        print(f"{job.decision:6} | {job.score:6.2f} | {job.company} | {job.title} | {job.url}")


if __name__ == "__main__":
    main()
