from __future__ import annotations

import argparse
import logging
import sys

from .discovery.sources import ArbeitnowSource, RemoteOKSource
from .pipeline import run_discovery_pipeline, run_pipeline


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Score and persist job offers")
    subparsers = parser.add_subparsers(dest="command", required=True)
    run = subparsers.add_parser("run", help="Run the CSV pipeline")
    run.add_argument("--input", required=True, help="Input CSV path")
    run.add_argument("--profile", default="config/profile.yaml", help="YAML profile path")
    run.add_argument("--database", default="data/jobs.db", help="SQLite database path")
    discover = subparsers.add_parser("discover", help="Discover, score and persist public jobs")
    discover.add_argument("--query", action="append", help="Query; may be supplied more than once")
    discover.add_argument("--location", help="Optional location filter")
    discover.add_argument("--limit", type=int, default=10, help="Maximum matches per source")
    discover.add_argument(
        "--source", action="append", choices=("remoteok", "arbeitnow"),
        help="Source; may be supplied more than once (default: all)",
    )
    discover.add_argument("--profile", default="config/profile.yaml", help="YAML profile path")
    discover.add_argument("--database", default="data/jobs.db", help="SQLite database path")
    return parser


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    args = build_parser().parse_args()
    if args.command == "run":
        result = run_pipeline(args.input, args.profile, args.database)
        print(f"Processed {len(result.jobs)} jobs ({result.inserted} inserted, {result.updated} updated)")
    else:
        factories = {"remoteok": RemoteOKSource, "arbeitnow": ArbeitnowSource}
        names = args.source or list(factories)
        result = run_discovery_pipeline(
            [factories[name]() for name in names], args.profile, args.database,
            queries=args.query, location=args.location, limit=args.limit,
        )
        print(f"Discovered {len(result.jobs)} jobs ({result.inserted} new, {result.updated} existing)")
        for name, stat in result.discovery.stats.items():
            status = f"ERROR {stat.error}" if stat.error else "OK"
            print(
                f"{name}: found={stat.found} accepted={stat.accepted} "
                f"duplicates={stat.duplicates} filtered={stat.filtered} status={status}"
            )
    for job in sorted(result.jobs, key=lambda item: item.score or 0, reverse=True)[:10]:
        print(f"{job.decision:6} | {job.score:6.2f} | {job.company} | {job.title} | {job.url}")


if __name__ == "__main__":
    main()
