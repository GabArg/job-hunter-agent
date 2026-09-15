from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import pytest

from job_hunter.database import JobDatabase
from job_hunter.discovery.aggregator import DiscoveryAggregator
from job_hunter.discovery.base import JobSource
from job_hunter.discovery.models import RawJob
from job_hunter.pipeline import run_discovery_pipeline


def raw(source: str, url: str | None = None) -> RawJob:
    return RawJob(url or source, "Data Analyst", source, "Argentina", "remote",
                  "SQL Excel", source, url or f"https://example.test/{source}",
                  datetime.now(timezone.utc).isoformat())


@dataclass
class TimedSource(JobSource):
    name: str
    delay: float = 0
    fail: bool = False
    threads: list[str] | None = None

    def discover(self, query, location=None, limit=None):
        if self.threads is not None: self.threads.append(threading.current_thread().name)
        time.sleep(self.delay)
        if self.fail: raise TimeoutError("target timed out")
        return [raw(self.name)]


def test_sources_execute_concurrently_and_outside_main_thread():
    threads: list[str] = []
    sources = [TimedSource(str(index), .12, threads=threads) for index in range(3)]
    started = time.perf_counter()
    result = DiscoveryAggregator(sources).discover("Data Analyst", max_workers=3)
    assert time.perf_counter() - started < .28
    assert result.sources_completed == 3
    assert all(name.startswith("discovery") for name in threads)


def test_slow_or_failed_source_does_not_cancel_others_and_timeout_is_recorded():
    sources = [TimedSource("fast"), TimedSource("slow", .08), TimedSource("broken", fail=True)]
    result = DiscoveryAggregator(sources).discover("Data Analyst", max_workers=3,
                                                   target_timeout_seconds=.02)
    assert {job.source for job in result.jobs} == {"fast", "slow"}
    assert result.stats["slow"].timed_out
    assert result.stats["broken"].error
    assert result.sources_completed == 3 and result.sources_failed == 2


def test_consolidation_is_deterministic_across_source_order():
    shared = "https://example.test/shared"
    first = DiscoveryAggregator([TimedSource("z"), TimedSource("a")]).discover("Data Analyst")
    second = DiscoveryAggregator([TimedSource("a"), TimedSource("z")]).discover("Data Analyst")
    assert [(job.source, job.url) for job in first.jobs] == [(job.source, job.url) for job in second.jobs]
    duplicate_first = DiscoveryAggregator([
        _StaticSource("z", raw("z", shared)), _StaticSource("a", raw("a", shared))]).discover("Data Analyst")
    duplicate_second = DiscoveryAggregator([
        _StaticSource("a", raw("a", shared)), _StaticSource("z", raw("z", shared))]).discover("Data Analyst")
    assert [(job.source, job.url) for job in duplicate_first.jobs] == [(job.source, job.url) for job in duplicate_second.jobs]


class _StaticSource(JobSource):
    def __init__(self, name, job): self.name, self.job = name, job
    def discover(self, query, location=None, limit=None): return [self.job]


def test_old_running_run_is_aborted_but_recent_run_is_untouched(tmp_path):
    database = JobDatabase(tmp_path / "runs.db")
    now = datetime.now(timezone.utc)
    old = database.create_discovery_run(["old"], (now - timedelta(hours=3)).isoformat())
    recent = database.create_discovery_run(["recent"], (now - timedelta(minutes=30)).isoformat())
    assert database.reconcile_stale_discovery_runs(now=now) == [old]
    rows = {row["id"]: row for row in database.list_discovery_runs()}
    assert rows[old]["status"] == "ABORTED" and rows[old]["finished_at"]
    assert "stale_run_recovered" in rows[old]["errors"]
    assert rows[recent]["status"] == "RUNNING" and rows[recent]["finished_at"] is None


def test_aborted_run_cannot_be_overwritten_by_late_worker_completion(tmp_path):
    database = JobDatabase(tmp_path / "late.db")
    run_id = database.create_discovery_run(["slow"])
    assert database.abort_discovery_run(run_id, "operator_timeout")
    database.finish_discovery_run(run_id, status="COMPLETED", fetched=9)
    row = database.latest_discovery_run()
    assert row["status"] == "ABORTED" and row["fetched"] == 0


def test_run_always_finishes_and_sqlite_stays_on_main_thread(tmp_path, monkeypatch):
    calls: list[str] = []
    original = JobDatabase._connect

    def tracked(self):
        calls.append(threading.current_thread().name)
        return original(self)

    monkeypatch.setattr(JobDatabase, "_connect", tracked)
    run_discovery_pipeline([TimedSource("ok")], "config/profile.example.yaml", tmp_path / "jobs.db",
                           queries=["Data Analyst"])
    row = JobDatabase(tmp_path / "jobs.db").latest_discovery_run()
    assert row["finished_at"] and row["status"] == "COMPLETED"
    assert set(calls) == {threading.current_thread().name}


def test_unexpected_pipeline_exception_still_finishes_run(tmp_path, monkeypatch):
    import job_hunter.pipeline as pipeline
    monkeypatch.setattr(pipeline, "process_jobs", lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("boom")))
    path = tmp_path / "failed.db"
    with pytest.raises(RuntimeError):
        run_discovery_pipeline([TimedSource("ok")], "config/profile.example.yaml", path,
                               queries=["Data Analyst"])
    row = JobDatabase(path).latest_discovery_run()
    assert row["status"] == "FAILED" and row["finished_at"] and row["fetched"] == 1
