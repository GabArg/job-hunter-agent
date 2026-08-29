from __future__ import annotations

import argparse

from .pipeline import run_pipeline


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Score and persist job offers")
    subparsers = parser.add_subparsers(dest="command", required=True)
    run = subparsers.add_parser("run", help="Run the CSV pipeline")
    run.add_argument("--input", required=True, help="Input CSV path")
    run.add_argument("--profile", default="config/profile.yaml", help="YAML profile path")
    run.add_argument("--database", default="data/jobs.db", help="SQLite database path")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    result = run_pipeline(args.input, args.profile, args.database)
    print(f"Processed {len(result.jobs)} jobs ({result.inserted} inserted, {result.updated} updated)")
    for job in result.jobs:
        print(f"{job.decision:6} | {job.score:6.2f} | {job.company} | {job.title} | {job.url}")


if __name__ == "__main__":
    main()
