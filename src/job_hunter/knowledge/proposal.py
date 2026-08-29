from __future__ import annotations

import hashlib
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from .models import ProposalStatus, ProposalType, UpdateProposal


class KnowledgeSource:
    def entries(self) -> list[dict[str, Any]]:
        raise NotImplementedError


class ManualKnowledgeSource(KnowledgeSource):
    def __init__(self, entries: list[dict[str, Any]]): self._entries = entries
    def entries(self) -> list[dict[str, Any]]: return list(self._entries)


class GitHubKnowledgeSource(KnowledgeSource):
    def entries(self) -> list[dict[str, Any]]:
        raise NotImplementedError("GitHub ingestion is intentionally not automatic")


class ProposalGenerator:
    def generate(self, entry: dict[str, Any], master_path: str | Path, reserved_ids: set[str] | None = None) -> UpdateProposal:
        master = yaml.safe_load(Path(master_path).read_text(encoding="utf-8")) or {}
        identifiers = _all_ids(master) | set(reserved_ids or set())
        kind = ProposalType(str(entry["type"]).upper())
        changes = self._changes(kind, entry, master, identifiers)
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        fingerprint = hashlib.sha256(yaml.safe_dump(entry, sort_keys=True).encode()).hexdigest()[:12]
        return UpdateProposal(
            id=str(entry.get("proposal_id") or f"proposal_{fingerprint}"), type=kind,
            status=ProposalStatus.DRAFT, created_at=now, updated_at=now,
            title=str(entry.get("title") or entry.get("program") or entry.get("project") or kind.value),
            source=str(entry.get("source") or "manual"), evidence=[str(value) for value in entry.get("evidence", [])],
            proposed_changes=changes, notes=str(entry.get("notes") or ""), confidence=float(entry.get("confidence", 1.0)),
        )

    def _changes(self, kind: ProposalType, entry: dict[str, Any], master: dict, ids: set[str]) -> dict[str, Any]:
        if kind in {ProposalType.COURSE, ProposalType.CERTIFICATION}:
            identifier = _next("course", ids); fact_id = f"{identifier}_fact_01"
            return {"operation": "add_course", "value": {
                "id": identifier, "institution": entry.get("institution", ""), "program": entry.get("program", ""),
                "status": entry.get("status", ""), "completed_at": entry.get("completed_at"),
                "facts": [{"id": fact_id, "text": entry.get("fact") or _course_fact(entry), "tags": entry.get("skills", [])}],
            }, "skills": entry.get("skills", [])}
        if kind == ProposalType.PROJECT:
            identifier = _next("project", ids)
            metrics = [
                {"id": f"{identifier}_metric_{number:02d}", "text": str(metric.get("text", "")) if isinstance(metric, dict) else str(metric)}
                for number, metric in enumerate(entry.get("metrics", []), 1)
            ]
            return {"operation": "add_project", "value": {
                "id": identifier, "name": entry.get("name") or entry.get("project"), "category": entry.get("category", ""),
                "facts": [{"id": f"{identifier}_fact_01", "text": entry.get("fact", ""), "tags": entry.get("tags", [])}],
                "metrics": metrics, "technologies": entry.get("technologies", []), "links": entry.get("links", []),
            }}
        if kind == ProposalType.PROJECT_UPDATE:
            project = _find(master.get("projects", []), entry.get("project"))
            prefix = project.get("id", "project") + "_fact"
            return {"operation": "add_project_fact", "target_id": project.get("id"), "value": {
                "id": _next_nested(prefix, ids), "text": entry.get("fact", ""), "tags": entry.get("tags", []),
            }, "technologies": entry.get("technologies", [])}
        if kind in {ProposalType.EXPERIENCE_UPDATE, ProposalType.ACHIEVEMENT}:
            experience = _find(master.get("experience", []), entry.get("experience") or entry.get("company"))
            prefix = experience.get("id", "exp") + "_fact"
            return {"operation": "add_experience_fact", "target_id": experience.get("id"), "value": {
                "id": _next_nested(prefix, ids), "text": entry.get("fact", ""), "tags": entry.get("tags", []),
            }}
        if kind == ProposalType.SKILL:
            return {"operation": "add_skill", "category": entry.get("category", "technology"), "value": entry.get("skill") or entry.get("title")}
        if kind == ProposalType.EXPERIENCE:
            identifier = _next("exp", ids)
            return {"operation": "add_experience", "value": {
                "id": identifier, "company": entry.get("company", ""), "role": entry.get("role", ""),
                "start_date": entry.get("start_date", ""), "end_date": entry.get("end_date", ""),
                "location": entry.get("location", ""),
                "facts": [{"id": f"{identifier}_fact_01", "text": entry.get("fact", ""), "tags": entry.get("tags", [])}],
                "technologies": entry.get("technologies", []),
            }}
        if kind == ProposalType.EDUCATION:
            identifier = _next("edu", ids)
            return {"operation": "add_education", "value": {
                "id": identifier, "institution": entry.get("institution", ""), "program": entry.get("program", ""),
                "status": entry.get("status", ""), "dates": entry.get("dates", ""),
                "facts": [{"id": f"{identifier}_fact_01", "text": entry.get("fact", ""), "tags": entry.get("tags", [])}],
            }}
        if kind == ProposalType.LANGUAGE:
            identifier = _next("lang", ids)
            facts = [] if not entry.get("fact") else [{"id": f"{identifier}_fact_01", "text": entry["fact"], "tags": entry.get("tags", [])}]
            return {"operation": "add_language", "value": {
                "id": identifier, "language": entry.get("language", ""), "level": entry.get("level", ""), "facts": facts,
            }}
        raise ValueError(f"Unsupported proposal type: {kind}")


def _course_fact(entry) -> str:
    skills = ", ".join(str(value) for value in entry.get("skills", []))
    return f"Formación en {skills}." if skills else str(entry.get("program", ""))


def _all_ids(value) -> set[str]:
    results = set()
    if isinstance(value, dict):
        if value.get("id"): results.add(str(value["id"]))
        for child in value.values(): results |= _all_ids(child)
    elif isinstance(value, list):
        for child in value: results |= _all_ids(child)
    return results


def _next(prefix: str, ids: set[str]) -> str:
    numbers = [int(match.group(1)) for value in ids if (match := re.fullmatch(rf"{re.escape(prefix)}_(\d+)", value))]
    return f"{prefix}_{max(numbers, default=0) + 1:02d}"


def _next_nested(prefix: str, ids: set[str]) -> str:
    numbers = [int(match.group(1)) for value in ids if (match := re.fullmatch(rf"{re.escape(prefix)}_(\d+)", value))]
    return f"{prefix}_{max(numbers, default=0) + 1:02d}"


def _find(entries: list[dict], target) -> dict:
    normalized = str(target or "").lower()
    result = next((item for item in entries if str(item.get("id", "")).lower() == normalized or str(item.get("name", item.get("company", ""))).lower() == normalized), None)
    if result is None: raise ValueError(f"Target not found in master: {target}")
    return result
