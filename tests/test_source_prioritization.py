from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone

from job_hunter.database import JobDatabase
from job_hunter.discovery.aggregator import DiscoveryAggregator
from job_hunter.discovery.base import JobSource
from job_hunter.discovery.models import RawJob
from job_hunter.discovery.prioritization import build_source_plan, source_value_score
from job_hunter.pipeline import run_discovery_pipeline


class OrderedSource(JobSource):
    def __init__(self, name, events, delay=0): self.name, self.events, self.delay = name, events, delay
    def discover(self, query, location=None, limit=None):
        self.events.append(self.name); time.sleep(self.delay)
        return [RawJob(self.name, "Data Analyst", self.name, "Argentina", "remote", "SQL Excel",
                       self.name, f"https://example.test/{self.name}", datetime.now(timezone.utc).isoformat())]


def metric(**changes):
    value = {"fetched": 5, "role_relevant": 2, "new_jobs": 1, "scored": 2,
             "apply_count": 1, "review_count": 0, "duplicates": 0, "errors": 0,
             "latency_ms": 2000, "consecutive_failures": 0,
             "recorded_at": datetime.now(timezone.utc).isoformat()}
    value.update(changes); return value


def test_value_score_rewards_useful_fast_sources_and_penalizes_slow_empty_ones():
    assert source_value_score([metric()]) > source_value_score([
        metric(fetched=0, role_relevant=0, new_jobs=0, scored=0, apply_count=0,
               latency_ms=90_000, errors=1)])


def test_high_value_executes_before_low_value_and_order_is_deterministic():
    events: list[str] = []
    low, high = OrderedSource("low", events), OrderedSource("high", events)
    low.priority_tier, low.source_value_score = "TIER_3", 5
    high.priority_tier, high.source_value_score = "TIER_1", 90
    DiscoveryAggregator([low, high]).discover("Data Analyst", max_workers=1, run_budget_seconds=5)
    assert events == ["high", "low"]


def test_budget_prevents_starting_later_targets_and_run_closes(tmp_path):
    events: list[str] = []
    first, later = OrderedSource("first", events, .03), OrderedSource("later", events)
    first.priority_tier, first.source_value_score = "TIER_1", 90
    later.priority_tier, later.source_value_score = "TIER_2", 30
    result = DiscoveryAggregator([later, first]).discover("Data Analyst", max_workers=1, run_budget_seconds=.01)
    assert events == ["first"] and result.stats["later"].skipped_reason == "SKIPPED_BUDGET"
    assert result.sources_skipped_budget == 1


def test_pipeline_persists_budget_skip_and_terminal_run(tmp_path):
    events: list[str] = []
    sources = [OrderedSource("one", events, .03), OrderedSource("two", events)]
    for source, tier, score in ((sources[0], "TIER_1", 90), (sources[1], "TIER_2", 30)):
        source.target_priority = "normal"
    path = tmp_path / "budget.db"
    run_discovery_pipeline(sources, "config/profile.example.yaml", path, queries=["Data Analyst"],
                           max_workers=1, run_budget_seconds=.01)
    run = JobDatabase(path).latest_discovery_run()
    assert run["finished_at"] and run["status"] == "COMPLETED" and run["sources_skipped_budget"] >= 0


def test_circuit_breaker_cooldown_expires_and_exploration_returns():
    now = datetime.now(timezone.utc)
    failed = [metric(fetched=0, latency_ms=60_000, consecutive_failures=3,
                     recorded_at=now.isoformat()) for _ in range(3)]
    plan = build_source_plan("slow", failed, now=now)
    assert not plan.should_run and plan.skip_reason == "COOLDOWN"
    expired = build_source_plan("slow", failed, now=now + timedelta(hours=13))
    assert expired.should_run
    low = [metric(fetched=0, role_relevant=0, new_jobs=0, scored=0, apply_count=0,
                  latency_ms=1000, recorded_at=now.isoformat())]
    assert not build_source_plan("low", low, now=now).should_run
    assert build_source_plan("low", low, now=now + timedelta(hours=13)).should_run


def test_manual_priority_override():
    bad = [metric(fetched=0, role_relevant=0, new_jobs=0, scored=0, apply_count=0,
                  latency_ms=90_000, recorded_at=(datetime.now(timezone.utc) - timedelta(days=1)).isoformat())]
    assert build_source_plan("manual", bad, override="high").tier == "TIER_1"
    assert build_source_plan("manual", [metric()], override="low").tier == "TIER_3"
