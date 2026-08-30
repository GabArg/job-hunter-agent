from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any

import yaml


class TargetHealth(StrEnum):
    HEALTHY = "HEALTHY"
    DEGRADED = "DEGRADED"
    DISABLED = "DISABLED"


@dataclass(slots=True)
class CompanyTarget:
    company: str
    sector: str = "Other"
    source_type: str = "manual_source_candidate"
    token: str = ""
    url: str = ""
    enabled: bool = True
    priority: str = "normal"
    notes: str = ""
    consecutive_failures: int = 0
    health: TargetHealth = TargetHealth.HEALTHY

    @property
    def id(self) -> str:
        return f"{self.source_type}:{self.company}".casefold()

    def register_result(self, error: str | None) -> None:
        self.consecutive_failures = self.consecutive_failures + 1 if error else 0
        if not self.enabled:
            self.health = TargetHealth.DISABLED
        else:
            self.health = TargetHealth.DEGRADED if self.consecutive_failures >= 3 else TargetHealth.HEALTHY


class TargetRegistry:
    def __init__(self, targets: list[CompanyTarget]):
        self.targets = targets

    @property
    def active(self) -> list[CompanyTarget]:
        return [target for target in self.targets if target.enabled and target.source_type in {"greenhouse", "lever", "ashby", "workable", "generic"}]

    @classmethod
    def from_mapping(cls, data: dict[str, Any]) -> "TargetRegistry":
        targets: list[CompanyTarget] = []
        nested = data.get("discovery_targets") or {}
        for source_type, values in nested.items():
            for value in values or []:
                targets.append(_target(value, str(source_type)))
        for value in data.get("career_pages") or []:
            targets.append(_target(value, "generic"))
        for value in data.get("career_targets") or []:
            targets.append(_target(value, str(value.get("ats") or value.get("source_type") or "generic")))
        return cls(_deduplicate(targets))

    @classmethod
    def from_configs(cls, public_path: str | Path, private_path: str | Path | None = None) -> "TargetRegistry":
        public = yaml.safe_load(Path(public_path).read_text(encoding="utf-8")) or {}
        merged = cls.from_mapping(public).targets
        if private_path and Path(private_path).exists():
            private = yaml.safe_load(Path(private_path).read_text(encoding="utf-8")) or {}
            merged = _merge(merged, cls.from_mapping(private).targets)
        return cls(merged)

    def counts_by_source(self) -> dict[str, int]:
        return _counts(target.source_type for target in self.targets)

    def counts_by_sector(self) -> dict[str, int]:
        return _counts(target.sector for target in self.targets)


def detect_sector(company: str, description: str) -> tuple[str, float]:
    text = f"{company} {description}".casefold()
    rules = {
        "Fintech": ("fintech", "payment", "pagos", "billetera", "financial technology"),
        "Banking": ("banco", "banking", "bank "), "Retail": ("retail", "supermercado", "consumo masivo"),
        "E-commerce": ("e-commerce", "ecommerce", "marketplace", "comercio electrónico"),
        "Consulting": ("consulting", "consultoría", "consultoria"), "Logistics": ("logística", "logistica", "logistics", "shipping"),
        "Telecom": ("telecom", "telecommunications"), "SaaS": ("saas", "software as a service"),
        "Technology": ("technology", "tecnología", "tecnologia", "software"),
    }
    matches = [sector for sector, signals in rules.items() if any(signal in text for signal in signals)]
    return (matches[0], 0.65) if len(matches) == 1 else (matches[0], 0.45) if matches else ("Other", 0.2)


def quality_score(fetched: int, relevant: int, apply: int, review: int, duplicates: int, errors: int, fresh: int = 0) -> float:
    if fetched <= 0: return 0.0 if errors else 50.0
    relevance = relevant / fetched
    useful = (apply + 0.6 * review) / max(1, relevant)
    duplicate_penalty = duplicates / max(1, fetched)
    error_penalty = min(1.0, errors)
    freshness = fresh / fetched
    return round(max(0.0, min(100.0, 45 * relevance + 30 * useful + 10 * freshness + 15 - 10 * duplicate_penalty - 25 * error_penalty)), 2)


def _target(value: dict[str, Any], source_type: str) -> CompanyTarget:
    return CompanyTarget(
        company=str(value.get("company") or "").strip(), sector=str(value.get("sector") or (value.get("sectors") or ["Other"])[0]),
        source_type=source_type.lower(), token=str(value.get("board_token") or value.get("token") or value.get("account") or ""),
        url=str(value.get("url") or value.get("careers_url") or ""), enabled=bool(value.get("enabled", True)),
        priority=str(value.get("priority") or "normal"), notes=str(value.get("notes") or ""),
    )


def _merge(public: list[CompanyTarget], private: list[CompanyTarget]) -> list[CompanyTarget]:
    values = {target.id: target for target in public}
    values.update({target.id: target for target in private})
    return list(values.values())


def _deduplicate(values: list[CompanyTarget]) -> list[CompanyTarget]:
    return _merge([], values)


def _counts(values) -> dict[str, int]:
    result: dict[str, int] = {}
    for value in values: result[value] = result.get(value, 0) + 1
    return result
