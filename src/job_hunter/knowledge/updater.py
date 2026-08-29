from __future__ import annotations

import copy
import os
import shutil
from datetime import datetime
from pathlib import Path
from typing import Callable

import yaml

from .audit import AuditLog
from .loader import ProposalStore
from .models import ProposalStatus, UpdateProposal
from .validator import validate_master_consistency, validate_proposal


class KnowledgeUpdater:
    def __init__(self, master_path: str | Path, proposals_path: str | Path, audit_path: str | Path,
                 backups_dir: str | Path, consistency_check: Callable[[str | Path], None] = validate_master_consistency):
        self.master_path, self.store = Path(master_path), ProposalStore(proposals_path)
        self.audit, self.backups_dir, self.consistency_check = AuditLog(audit_path), Path(backups_dir), consistency_check

    def create(self, proposal: UpdateProposal) -> UpdateProposal:
        if any(item.id == proposal.id or _fingerprint(item) == _fingerprint(proposal) for item in self.store.list()): raise ValueError("Duplicate proposal")
        self.store.upsert(proposal); self.audit.record(proposal.id, "CREATE", None, proposal.status.value, proposal.proposed_changes, "created")
        return proposal

    def validate(self, proposal_id: str) -> UpdateProposal:
        proposal = self.store.get(proposal_id); previous = proposal.status.value
        if proposal.status in {ProposalStatus.APPROVED, ProposalStatus.APPLIED, ProposalStatus.REJECTED}: raise ValueError(f"Cannot validate proposal in {proposal.status.value}")
        validate_proposal(proposal, self.master_path); self.store.upsert(proposal)
        self.audit.record(proposal.id, "VALIDATE", previous, proposal.status.value, proposal.proposed_changes, "valid" if not proposal.validation_errors else "invalid")
        return proposal

    def approve(self, proposal_id: str) -> UpdateProposal:
        proposal = self.store.get(proposal_id)
        if proposal.status != ProposalStatus.PENDING_APPROVAL: raise ValueError("Only PENDING_APPROVAL proposals can be approved")
        previous = proposal.status.value; proposal.status = ProposalStatus.APPROVED; proposal.touch(); self.store.upsert(proposal)
        self.audit.record(proposal.id, "APPROVE", previous, proposal.status.value, {}, "approved"); return proposal

    def reject(self, proposal_id: str) -> UpdateProposal:
        proposal = self.store.get(proposal_id)
        if proposal.status == ProposalStatus.APPLIED: raise ValueError("An APPLIED proposal cannot be rejected")
        previous = proposal.status.value; proposal.status = ProposalStatus.REJECTED; proposal.touch(); self.store.upsert(proposal)
        self.audit.record(proposal.id, "REJECT", previous, proposal.status.value, {}, "rejected"); return proposal

    def preview(self, proposal_id: str) -> str: return preview_master_change(self.store.get(proposal_id), self.master_path)

    def apply(self, proposal_id: str) -> UpdateProposal:
        proposal = self.store.get(proposal_id)
        if proposal.status != ProposalStatus.APPROVED: raise ValueError("Apply requires APPROVED status")
        self.backups_dir.mkdir(parents=True, exist_ok=True)
        backup = self.backups_dir / f"master_cv_{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}.yaml"
        shutil.copy2(self.master_path, backup)
        temporary = self.master_path.with_name(f".{self.master_path.name}.{proposal.id}.tmp")
        try:
            master = yaml.safe_load(self.master_path.read_text(encoding="utf-8")) or {}
            temporary.write_text(yaml.safe_dump(_apply_change(copy.deepcopy(master), proposal.proposed_changes), sort_keys=False, allow_unicode=True), encoding="utf-8")
            self.consistency_check(temporary); os.replace(temporary, self.master_path); self.consistency_check(self.master_path)
        except Exception as exc:
            if temporary.exists(): temporary.unlink()
            shutil.copy2(backup, self.master_path)
            self.audit.record(proposal.id, "ROLLBACK", proposal.status.value, proposal.status.value, proposal.proposed_changes, f"rolled back: {exc}")
            raise
        previous = proposal.status.value; proposal.status = ProposalStatus.APPLIED; proposal.touch(); self.store.upsert(proposal)
        self.audit.record(proposal.id, "APPLY", previous, proposal.status.value, proposal.proposed_changes, f"applied; backup={backup.name}")
        return proposal


def preview_master_change(proposal: UpdateProposal, master: str | Path | dict) -> str:
    current = yaml.safe_load(Path(master).read_text(encoding="utf-8")) if not isinstance(master, dict) else master
    _apply_change(copy.deepcopy(current or {}), proposal.proposed_changes)
    lines = [f"# {proposal.proposed_changes.get('operation', 'change')}"]
    lines.extend(f"+ {line}" for line in yaml.safe_dump(proposal.proposed_changes.get("value"), sort_keys=False, allow_unicode=True).rstrip().splitlines())
    if proposal.proposed_changes.get("technologies"):
        lines.append("+ technologies:"); lines.extend(f"+ - {item}" for item in proposal.proposed_changes["technologies"])
    return "\n".join(lines)


def _apply_change(master: dict, changes: dict) -> dict:
    operation, value = changes.get("operation"), copy.deepcopy(changes.get("value"))
    if operation == "add_course":
        master.setdefault("courses", []).append(value)
        for skill in changes.get("skills", []):
            category = _skill_category(master, skill)
            if not any(str(skill).casefold() == str(item).casefold() for item in master.setdefault("skills", {}).setdefault(category, [])): master["skills"][category].append(skill)
    elif operation == "add_project": master.setdefault("projects", []).append(value)
    elif operation in {"add_project_fact", "add_experience_fact"}:
        section = "projects" if operation == "add_project_fact" else "experience"
        target = next((item for item in master.get(section, []) if item.get("id") == changes.get("target_id")), None)
        if target is None: raise ValueError(f"Target not found: {changes.get('target_id')}")
        target.setdefault("facts", []).append(value)
        if operation == "add_project_fact":
            for technology in changes.get("technologies", []):
                if technology not in target.setdefault("technologies", []): target["technologies"].append(technology)
    elif operation == "add_skill": master.setdefault("skills", {}).setdefault(changes["category"], []).append(value)
    elif operation in {"add_experience", "add_education", "add_language"}:
        master.setdefault({"add_experience": "experience", "add_education": "education", "add_language": "languages"}[operation], []).append(value)
    else: raise ValueError(f"Unsupported operation: {operation}")
    return master


def _skill_category(master: dict, skill: str) -> str:
    for category, values in (master.get("skills") or {}).items():
        if any(str(skill).casefold() == str(value).casefold() for value in values): return category
    return "technology"


def _fingerprint(proposal: UpdateProposal) -> str:
    return yaml.safe_dump({"type": proposal.type.value, "changes": proposal.proposed_changes}, sort_keys=True)
