from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from .models import UpdateProposal


class ProposalStore:
    def __init__(self, path: str | Path):
        self.path = Path(path)

    def list(self) -> list[UpdateProposal]:
        if not self.path.exists(): return []
        data = yaml.safe_load(self.path.read_text(encoding="utf-8")) or {}
        return [UpdateProposal.from_dict(item) for item in data.get("proposals", [])]

    def save(self, proposals: list[UpdateProposal]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            yaml.safe_dump({"proposals": [proposal.to_dict() for proposal in proposals]}, sort_keys=False, allow_unicode=True),
            encoding="utf-8",
        )

    def get(self, proposal_id: str) -> UpdateProposal:
        proposal = next((item for item in self.list() if item.id == proposal_id), None)
        if proposal is None: raise KeyError(f"Proposal not found: {proposal_id}")
        return proposal

    def upsert(self, proposal: UpdateProposal) -> None:
        proposals = self.list()
        for index, current in enumerate(proposals):
            if current.id == proposal.id:
                proposals[index] = proposal
                self.save(proposals)
                return
        proposals.append(proposal)
        self.save(proposals)


def load_learning_log(path: str | Path) -> list[dict[str, Any]]:
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    return [dict(item) for item in data.get("entries", [])]
