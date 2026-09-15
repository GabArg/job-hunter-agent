from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any


@dataclass(frozen=True, slots=True)
class SourcePlan:
    source: str
    tier: str
    value_score: float
    cooldown_until: str | None = None
    should_run: bool = True
    skip_reason: str | None = None


def source_value_score(rows: list[dict[str, Any]]) -> float:
    """Simple discovery utility score over recent runs (0..100)."""
    rows = [row for row in rows if not row.get("skipped_reason")]
    if not rows: return 30.0
    runs = len(rows); fetched = sum(int(row.get("fetched") or 0) for row in rows)
    relevant = sum(int(row.get("role_relevant", row.get("relevant_after_description", 0)) or 0) for row in rows)
    new = sum(int(row.get("new_jobs") or 0) for row in rows)
    scored = sum(int(row.get("scored") or 0) for row in rows)
    apply = sum(int(row.get("apply_count") or 0) for row in rows)
    review = sum(int(row.get("review_count") or 0) for row in rows)
    duplicates = sum(int(row.get("duplicates") or 0) for row in rows)
    errors = sum(int(row.get("errors") or 0) for row in rows)
    average_latency_s = sum(int(row.get("latency_ms") or 0) for row in rows) / runs / 1000
    empty_rate = sum(int(row.get("fetched") or 0) == 0 for row in rows) / runs
    duplicate_rate = duplicates / max(1, fetched + duplicates)
    positive = (min(30.0, new / runs * 15) + min(9.0, scored / runs * 3) +
                min(30.0, apply / runs * 15) + min(16.0, review / runs * 8) +
                min(10.0, relevant / max(1, fetched) * 10))
    negative = min(25.0, average_latency_s * .35) + errors * 6 + empty_rate * 12 + duplicate_rate * 4
    return round(max(0.0, min(100.0, 15 + positive - negative)), 2)


def build_source_plan(source: str, rows: list[dict[str, Any]], override: str = "normal",
                      now: datetime | None = None, cooldown_hours: float = 12.0,
                      exploration_hours: float = 12.0) -> SourcePlan:
    reference = now or datetime.now(timezone.utc)
    rows = [row for row in rows if not row.get("skipped_reason")]
    score = source_value_score(rows)
    tier = "TIER_2" if not rows else "TIER_1" if score >= 28 else "TIER_2" if score >= 15 else "TIER_3"
    if override == "high": tier = "TIER_1"
    elif override == "low": tier = "TIER_3"
    recent = rows[0] if rows else {}
    failures = int(recent.get("consecutive_failures") or 0)
    three_empty = len(rows) >= 3 and all(int(row.get("fetched") or 0) == 0 for row in rows[:3])
    high_latency = sum(int(row.get("latency_ms") or 0) for row in rows[:3]) / max(1, min(3, len(rows))) >= 30_000
    last_run = _datetime(recent.get("recorded_at"))
    circuit_open = failures >= 3 or (three_empty and high_latency)
    cooldown_until = last_run + timedelta(hours=cooldown_hours) if circuit_open and last_run else None
    if cooldown_until and reference < cooldown_until:
        return SourcePlan(source, tier, score, cooldown_until.isoformat(timespec="seconds"), False, "COOLDOWN")
    if tier == "TIER_3" and last_run and reference < last_run + timedelta(hours=exploration_hours):
        return SourcePlan(source, tier, score, (last_run + timedelta(hours=exploration_hours)).isoformat(timespec="seconds"),
                          False, "EXPLORATION_NOT_DUE")
    return SourcePlan(source, tier, score)


def _datetime(value: Any) -> datetime | None:
    if not value: return None
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    return parsed.replace(tzinfo=parsed.tzinfo or timezone.utc).astimezone(timezone.utc)
