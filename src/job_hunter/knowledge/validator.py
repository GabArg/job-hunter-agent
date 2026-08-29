from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from .models import ProposalStatus, UpdateProposal

ALLOWED_EVIDENCE = {"manual_confirmation", "certificate", "course_completion", "github_commit", "github_repo", "document", "url", "project_output"}
COMPLETED_STATES = {"completed", "finalizado", "finalizada", "graduate", "graduado"}


def validate_proposal(proposal: UpdateProposal, master_path: str | Path) -> UpdateProposal:
    master = yaml.safe_load(Path(master_path).read_text(encoding="utf-8")) or {}
    errors: list[str] = []
    changes, value = proposal.proposed_changes, proposal.proposed_changes.get("value")
    operation = changes.get("operation")
    if not proposal.title.strip(): errors.append("title is required")
    if not proposal.evidence: errors.append("at least one evidence item is required")
    invalid = sorted(set(proposal.evidence) - ALLOWED_EVIDENCE)
    if invalid: errors.append(f"unsupported evidence: {', '.join(invalid)}")
    if not 0 <= proposal.confidence <= 1: errors.append("confidence must be between 0 and 1")
    if not operation: errors.append("proposed operation is required")
    collisions = sorted(_all_ids(master) & _all_ids(value))
    if collisions: errors.append(f"ID collision: {', '.join(collisions)}")
    if len(_all_ids(value)) != _count_ids(value): errors.append("duplicate IDs inside proposed change")

    if operation == "add_course":
        _required(value, ("id", "institution", "program", "status"), errors)
        if str((value or {}).get("status", "")).strip().lower() not in COMPLETED_STATES:
            errors.append("course must be completed before incorporation")
        if _same(master.get("courses", []), value, ("institution", "program")): errors.append("duplicate course")
    elif operation == "add_project":
        _required(value, ("id", "name"), errors)
        if not (value or {}).get("facts"): errors.append("project requires at least one factual statement")
        if _same(master.get("projects", []), value, ("name",)): errors.append("duplicate project")
    elif operation in {"add_project_fact", "add_experience_fact"}:
        section = "projects" if operation == "add_project_fact" else "experience"
        target = _by_id(master.get(section, []), changes.get("target_id"))
        if target is None: errors.append(f"target does not exist: {changes.get('target_id')}")
        _required(value, ("id", "text"), errors)
        if target and any(_norm(item.get("text")) == _norm((value or {}).get("text")) for item in target.get("facts", [])):
            errors.append("duplicate fact")
    elif operation == "add_skill":
        category, skill = str(changes.get("category", "")), str(value or "").strip()
        if not category or not skill: errors.append("skill and category are required")
        if category not in (master.get("skills") or {}): errors.append(f"unknown skill category: {category}")
        if any(_norm(skill) == _norm(existing) for skills in (master.get("skills") or {}).values() for existing in skills): errors.append("duplicate skill")
    elif operation == "add_experience":
        _required(value, ("id", "company", "role", "start_date", "end_date"), errors)
        if not (value or {}).get("facts"): errors.append("experience requires at least one factual statement")
        if _same(master.get("experience", []), value, ("company", "role", "start_date")): errors.append("duplicate experience")
    elif operation == "add_education":
        _required(value, ("id", "institution", "program", "status"), errors)
        if _same(master.get("education", []), value, ("institution", "program")): errors.append("duplicate education")
    elif operation == "add_language":
        _required(value, ("id", "language", "level"), errors)
        if _same(master.get("languages", []), value, ("language",)): errors.append("duplicate language")
    elif operation not in {"add_experience", "add_education", "add_language"}:
        errors.append(f"unsupported operation: {operation}")
    proposal.validation_errors = errors
    proposal.status = ProposalStatus.DRAFT if errors else ProposalStatus.PENDING_APPROVAL
    proposal.touch()
    return proposal


def validate_master_consistency(path: str | Path) -> None:
    from job_hunter.cv.loader import load_master_cv
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    if len(_all_ids(raw)) != _count_ids(raw): raise ValueError("Master contains duplicate IDs")
    load_master_cv(path)


def _required(value: Any, fields: tuple[str, ...], errors: list[str]) -> None:
    if not isinstance(value, dict): errors.append("structured value is required"); return
    for field in fields:
        if not str(value.get(field, "")).strip(): errors.append(f"{field} is required")


def _by_id(items: list[dict], identifier: Any) -> dict | None:
    return next((item for item in items if str(item.get("id")) == str(identifier)), None)


def _same(items: list[dict], value: dict | None, fields: tuple[str, ...]) -> bool:
    return bool(value) and any(all(_norm(item.get(field)) == _norm(value.get(field)) for field in fields) for item in items)


def _norm(value: Any) -> str: return " ".join(str(value or "").casefold().split())


def _all_ids(value: Any) -> set[str]:
    result: set[str] = set()
    if isinstance(value, dict):
        if value.get("id") is not None: result.add(str(value["id"]))
        for child in value.values(): result |= _all_ids(child)
    elif isinstance(value, list):
        for child in value: result |= _all_ids(child)
    return result


def _count_ids(value: Any) -> int:
    if isinstance(value, dict): return (1 if value.get("id") is not None else 0) + sum(_count_ids(child) for child in value.values())
    if isinstance(value, list): return sum(_count_ids(child) for child in value)
    return 0
