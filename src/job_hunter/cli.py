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
from .discovery.lock import DiscoveryAlreadyRunning, DiscoveryLock
from .knowledge import KnowledgeUpdater, ProposalGenerator
from .operations import generate_job_cv


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
    discover.add_argument("--limit", type=int, default=25, help="Maximum matches per target (default: 25)")
    discover.add_argument("--max-age-days", type=int, default=14, help="Maximum posting age (default: 14)")
    discover.add_argument(
        "--source", action="append",
        choices=("remoteok", "arbeitnow", "greenhouse", "lever", "ashby", "workable", "smartrecruiters", "recruitee", "generic"),
        help="Source; may be supplied more than once (default: all)",
    )
    discover.add_argument("--profile", default="config/profile.yaml", help="YAML profile path")
    discover.add_argument("--database", default="data/jobs.db", help="SQLite database path")
    report = subparsers.add_parser("discovery-report", help="Report source/target coverage and quality")
    report.add_argument("--profile", default="config/profile.yaml")
    report.add_argument("--database", default="data/jobs.db")
    report.add_argument("--sector")
    probe = subparsers.add_parser("probe-target", help="Probe one configured/public ATS URL without changing config")
    probe.add_argument("target", help="HTTPS careers URL or company present in profile")
    probe.add_argument("--profile", default="config/profile.yaml")
    probes = subparsers.add_parser("probe-targets", help="Probe configured candidate targets only")
    probes.add_argument("--profile", default="config/profile.yaml")
    probes.add_argument("--output", default="data/reports")
    cleanup = subparsers.add_parser("cleanup-old-jobs", help="Safely report or remove expired unprotected jobs")
    cleanup.add_argument("--profile", default="config/profile.yaml")
    cleanup.add_argument("--database", default="data/jobs.db")
    cleanup_mode = cleanup.add_mutually_exclusive_group(required=True)
    cleanup_mode.add_argument("--dry-run", action="store_true")
    cleanup_mode.add_argument("--apply", action="store_true")
    fix_modes = subparsers.add_parser("fix-work-modes", help="Normalize invalid persisted work modes")
    fix_modes.add_argument("--database", default="data/jobs.db")
    fix_mode = fix_modes.add_mutually_exclusive_group(required=True)
    fix_mode.add_argument("--dry-run", action="store_true")
    fix_mode.add_argument("--apply", action="store_true")
    enrich = subparsers.add_parser("enrich-job-sectors", help="Safely reclassify persisted job sectors")
    enrich.add_argument("--database", default="data/jobs.db")
    enrich.add_argument("--manual-only", action="store_true")
    enrich_mode = enrich.add_mutually_exclusive_group(required=True)
    enrich_mode.add_argument("--dry-run", action="store_true")
    enrich_mode.add_argument("--apply", action="store_true")
    cv = subparsers.add_parser("cv", help="Generate a factually validated tailored CV")
    target = cv.add_mutually_exclusive_group(required=True)
    target.add_argument("--job-id", type=int, help="Stored job ID")
    target.add_argument("--url", help="Stored job URL")
    cv.add_argument("--master-cv", default="private/master_cv.yaml", help="Private factual master CV")
    cv.add_argument("--output", default="outputs", help="Output directory")
    cv.add_argument("--database", default="data/jobs.db", help="SQLite database path")
    cv.add_argument("--allow-reject", action="store_true", help="Explicitly allow CV for a REJECT job")
    generate_cv = subparsers.add_parser("generate-cv", help="Generate and validate HTML + PDF for one job")
    generate_cv.add_argument("job_id", type=int)
    generate_cv.add_argument("--master-cv", default="private/master_cv.yaml")
    generate_cv.add_argument("--output", default="outputs/cvs")
    generate_cv.add_argument("--database", default="data/jobs.db")
    generate_cv.add_argument("--allow-reject", action="store_true")
    knowledge = subparsers.add_parser("knowledge", help="Manage approval-gated factual updates")
    knowledge.add_argument("--master-cv", default="private/master_cv.yaml")
    knowledge.add_argument("--proposals", default="private/update_proposals.yaml")
    knowledge.add_argument("--audit", default="private/knowledge_audit.jsonl")
    knowledge.add_argument("--backups", default="private/backups")
    actions = knowledge.add_subparsers(dest="knowledge_action", required=True)
    actions.add_parser("list", help="List proposals")
    add = actions.add_parser("add", help="Create a DRAFT proposal")
    add.add_argument("--type", required=True, choices=("COURSE", "CERTIFICATION", "PROJECT", "PROJECT_UPDATE", "SKILL", "EXPERIENCE", "EXPERIENCE_UPDATE", "EDUCATION", "LANGUAGE", "ACHIEVEMENT"))
    add.add_argument("--title", required=True)
    add.add_argument("--institution"); add.add_argument("--program"); add.add_argument("--status")
    add.add_argument("--company"); add.add_argument("--role"); add.add_argument("--start-date"); add.add_argument("--end-date")
    add.add_argument("--language"); add.add_argument("--level"); add.add_argument("--dates"); add.add_argument("--location")
    add.add_argument("--project"); add.add_argument("--experience"); add.add_argument("--fact", action="append", default=[])
    add.add_argument("--category"); add.add_argument("--completed-at")
    add.add_argument("--evidence", action="append", default=[])
    add.add_argument("--skill", action="append", default=[])
    add.add_argument("--technology", action="append", default=[])
    add.add_argument("--link", action="append", default=[])
    for name in ("validate", "approve", "reject", "preview", "apply"):
        action = actions.add_parser(name); action.add_argument("proposal_id")
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
        try:
            with DiscoveryLock(Path(args.database).parent / "discovery.lock"):
                result = run_discovery_pipeline(
                    build_sources(profile, args.source), args.profile, args.database,
                    queries=queries or None, location=args.location, limit=args.limit,
                    max_age_days=args.max_age_days,
                )
        except DiscoveryAlreadyRunning as exc:
            print(str(exc)); return
        print(f"Discovered {len(result.jobs)} jobs ({result.inserted} new, {result.updated} existing)")
        for name, stat in result.discovery.stats.items():
            status = f"ERROR {stat.error}" if stat.error else "OK"
            print(
                f"{name}: fetched={stat.fetched} title_relevant={stat.relevant_by_title} "
                f"description_relevant={stat.relevant_after_description} pre_score_rejected={stat.rejected_pre_score} "
                f"scored={stat.scored} APPLY={stat.apply_count} REVIEW={stat.review_count} REJECT={stat.reject_count} "
                f"duplicates={stat.duplicates} latency_ms={stat.latency_ms} status={status}"
            )
    elif args.command == "discovery-report":
        from .discovery.target_registry import TargetRegistry
        profile = load_profile(args.profile); database = JobDatabase(args.database)
        registry = TargetRegistry.from_mapping({"discovery_targets": profile.discovery_targets,
                                                "active_targets": profile.active_targets,
                                                "candidate_targets": profile.candidate_targets,
                                                "career_pages": profile.career_pages,
                                                "career_targets": profile.career_targets})
        report = database.discovery_report()
        intelligence = database.source_intelligence(args.sector)
        print(f"Targets activos: {len(registry.active)} / {len(registry.targets)}")
        print("Por ATS: " + ", ".join(f"{k}={v}" for k, v in sorted(registry.counts_by_source().items())))
        print("Por sector: " + ", ".join(f"{k}={v}" for k, v in sorted(registry.counts_by_sector().items())))
        print(f"Jobs últimos 7 días: {report['jobs_last_7_days']} | decisiones={report['decisions']}")
        for row in intelligence:
            print(f"{row['source']} | {row['target']} | {row['sector']} | {row['health']} | "
                  f"fetched={row['fetched']} relevant={row['relevant']} APPLY={row['apply_count']} "
                  f"REVIEW={row['review_count']} REJECT={row['reject_count']} quality={row['quality_score']}")
        return
    elif args.command in {"probe-target", "probe-targets"}:
        import json
        from .discovery.probe import probe_target, write_probe_report
        from .discovery.target_registry import TargetRegistry
        profile = load_profile(args.profile)
        registry = TargetRegistry.from_mapping({"discovery_targets": profile.discovery_targets,
            "active_targets": profile.active_targets, "candidate_targets": profile.candidate_targets,
            "career_pages": profile.career_pages, "career_targets": profile.career_targets})
        if args.command == "probe-target":
            configured = next((item for item in registry.targets if item.company.casefold() == args.target.casefold()), None)
            result = probe_target(configured or args.target)
            print(json.dumps(result.as_dict(), ensure_ascii=False, indent=2)); return
        candidates = [target for target in registry.candidates if target.url]
        results = [probe_target(target) for target in candidates]
        output = write_probe_report(results, args.output)
        print(f"Probed {len(results)} candidates | report={output}")
        for result in results:
            print(f"{result.company} | {result.detected_source_type} | {result.status} | jobs={result.jobs_found}")
        return
    elif args.command == "cleanup-old-jobs":
        profile = load_profile(args.profile)
        result = JobDatabase(args.database).cleanup_old_jobs(profile.max_age_days, apply=args.apply)
        print(f"Threshold: {result['threshold']} | max_age_days={profile.max_age_days}")
        for row in result["eligible"]:
            print(f"ELIGIBLE | {row['id']} | {row['company']} | {row['title']} | {row['published_at']} | {row['decision']} | {row['application_status']}")
        for row in result["protected"]:
            print(f"PROTECTED_OLD_JOB | {row['id']} | {row['company']} | {row['title']} | {row['published_at']} | {row['decision']} | {row['application_status']}")
        print(f"Eligible={len(result['eligible'])} Protected={len(result['protected'])} Deleted={result['deleted']}")
        if result["backup"]: print(f"Backup: {result['backup']}")
        return
    elif args.command == "fix-work-modes":
        changes = JobDatabase(args.database).repair_invalid_work_modes(apply=args.apply)
        for row in changes:
            print(f"{row['job_id']} | {row['company']} | {row['title']} | {row['before']} -> {row['after']}")
        print(f"Changed={len(changes) if args.apply else 0} Candidates={len(changes)}")
        return
    elif args.command == "enrich-job-sectors":
        result = JobDatabase(args.database).enrich_job_sectors(manual_only=args.manual_only, apply=args.apply)
        for row in result["changes"]:
            print(f"{row['job_id']} | {row['company']} | {row['title']} | "
                  f"{row['sector_before']} ({row['confidence_before']:.2f}) -> "
                  f"{row['sector_after']} ({row['confidence_after']:.2f})")
        print(f"Candidates={len(result['changes'])} Updated={result['updated']}")
        if result["backup"]:
            print(f"Backup: {result['backup']}")
        return
    elif args.command == "cv":
        job = JobDatabase(args.database).get_job(args.job_id, args.url)
        if job is None:
            raise SystemExit("Job not found in SQLite")
        adapted = adapt_cv(job, load_master_cv(args.master_cv), allow_reject=args.allow_reject)
        safe_name = "".join(character if character.isalnum() else "-" for character in job.title).strip("-").lower()
        output = HTMLCVRenderer().render_to_file(adapted, Path(args.output) / f"cv-{job.id}-{safe_name}.html")
        print(f"CV {adapted.validation_status} | {adapted.approval_state} | {output}")
        return
    elif args.command == "generate-cv":
        html, adapted = generate_job_cv(args.database, args.job_id, args.master_cv, args.output, args.allow_reject)
        row = JobDatabase(args.database).get_job_row(args.job_id)
        print(f"Job #{args.job_id} | {adapted.job_title} | {adapted.company}")
        print(f"HTML: {adapted.validation_status} | {html}")
        print(f"PDF: {row['cv_pdf_status']} | Pages: {row['cv_pdf_pages']}")
        print(f"Output: {row['cv_pdf_path']}")
        return
    else:
        updater = KnowledgeUpdater(args.master_cv, args.proposals, args.audit, args.backups)
        if args.knowledge_action == "list":
            for proposal in updater.store.list():
                print(f"{proposal.id} | {proposal.type.value} | {proposal.status.value} | {proposal.title}")
            return
        if args.knowledge_action == "add":
            entry = {key: value for key, value in {
                "type": args.type, "title": args.title, "institution": args.institution,
                "program": args.program or args.title, "status": args.status,
                "company": args.company, "role": args.role, "start_date": args.start_date,
                "end_date": args.end_date, "language": args.language, "level": args.level,
                "dates": args.dates, "location": args.location,
                "completed_at": args.completed_at, "project": args.project,
                "experience": args.experience, "fact": args.fact[0] if args.fact else None,
                "facts": args.fact, "category": args.category,
                "evidence": args.evidence, "skills": args.skill, "technologies": args.technology,
                "links": args.link,
            }.items() if value not in (None, [], "")}
            reserved = {identifier for proposal in updater.store.list() for identifier in _proposal_ids(proposal.proposed_changes)}
            proposal = updater.create(ProposalGenerator().generate(entry, args.master_cv, reserved))
            print(f"{proposal.id} | {proposal.status.value} | {proposal.title}")
            return
        if args.knowledge_action == "preview":
            print(updater.preview(args.proposal_id))
            return
        operation = getattr(updater, args.knowledge_action)
        if args.knowledge_action == "apply":
            print(updater.preview(args.proposal_id))
        proposal = operation(args.proposal_id)
        print(f"{proposal.id} | {proposal.status.value}")
        if proposal.validation_errors:
            print("Errors: " + "; ".join(proposal.validation_errors))
        return
    for job in result.jobs[:20]:
        print(f"{job.decision:6} | {job.score:6.2f} | {job.company} | {job.title} | {job.url}")


def _proposal_ids(value):
    if isinstance(value, dict):
        if value.get("id"): yield str(value["id"])
        for child in value.values(): yield from _proposal_ids(child)
    elif isinstance(value, list):
        for child in value: yield from _proposal_ids(child)


if __name__ == "__main__":
    main()
