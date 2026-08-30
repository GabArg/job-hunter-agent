from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone

import yaml

from job_hunter.cli import build_parser
from job_hunter.config import load_profile
from job_hunter.database import JobDatabase
from job_hunter.discovery.aggregator import DiscoveryAggregator
from job_hunter.discovery.base import JobSource
from job_hunter.discovery.factory import build_sources
from job_hunter.discovery.matching import description_relevant, is_priority_fresh
from job_hunter.discovery.models import RawJob
from job_hunter.discovery.target_registry import CompanyTarget, TargetHealth, TargetRegistry, detect_sector, quality_score
from job_hunter.models import Job
from job_hunter.normalizer import normalize_job
from job_hunter.pipeline import run_discovery_pipeline
from job_hunter.scorer import score_job


def raw(url="https://example.test/job", title="Data Analyst", description="SQL data analytics", source="mock"):
    return RawJob(url, title, "Example", "Buenos Aires, Argentina", "hybrid", description,
                  source, url, datetime.now(timezone.utc).isoformat())


@dataclass
class FakeSource(JobSource):
    name: str
    jobs: list[RawJob]
    sector: str = "Other"
    target_id: str = "mock:example"

    def discover(self, query, location=None, limit=None):
        return self.jobs[:limit]


class BrokenTarget(JobSource):
    name = "lever:broken"; sector = "Fintech"; target_id = "lever:broken"
    def discover(self, query, location=None, limit=None): raise TimeoutError("down")


def test_target_registry_loads_and_merges_public_private(tmp_path):
    public = {"discovery_targets": {"lever": [{"company": "A", "board_token": "a", "sector": "Fintech"}]}}
    private = {"discovery_targets": {"lever": [{"company": "A", "board_token": "private", "enabled": False},
                                                     {"company": "B", "board_token": "b"}]}}
    p1, p2 = tmp_path / "public.yaml", tmp_path / "private.yaml"
    p1.write_text(yaml.safe_dump(public), encoding="utf-8"); p2.write_text(yaml.safe_dump(private), encoding="utf-8")
    registry = TargetRegistry.from_configs(p1, p2)
    assert len(registry.targets) == 2
    assert next(t for t in registry.targets if t.company == "A").token == "private"


def test_disabled_target_is_not_consulted_and_legacy_config_works():
    profile = load_profile("config/profile.example.yaml")
    profile = replace(profile,
        discovery_targets={"lever": [{"company": "Off", "board_token": "off", "enabled": False}]},
        career_pages=[], career_targets=[{"company": "Legacy", "ats": "lever", "board_token": "legacy"}])
    sources = build_sources(profile, ["lever"])
    assert [source.name for source in sources] == ["lever:Legacy"]


def test_query_groups_are_bilingual():
    groups = load_profile("config/profile.example.yaml").query_groups
    assert "data analyst" in groups["data"] and "analista de datos" in groups["data"]
    assert "business analyst" in groups["business"] and "analista de negocios" in groups["business"]


def test_analista_comercial_analytical_enters_and_sales_is_filtered():
    assert description_relevant("Analista Comercial", "Análisis de KPIs, márgenes, Excel y reporting")
    assert not description_relevant("Analista Comercial", "Venta directa, prospección, cartera y comisión")


def test_sector_metadata_and_fallback():
    source = FakeSource("mock", [raw()], sector="Fintech")
    result = DiscoveryAggregator([source]).discover("Data Analyst", preferred_locations=["Argentina"])
    assert result.jobs[0].sector == "Fintech" and result.jobs[0].sector_confidence == 1
    assert detect_sector("Example", "logística y shipping")[0] == "Logistics"


def test_source_metrics_and_quality_score(tmp_path):
    result = run_discovery_pipeline([FakeSource("Mock", [raw(source="Mock")], sector="Technology")],
                                    "config/profile.example.yaml", tmp_path / "jobs.db", queries=["Data Analyst"])
    metric = JobDatabase(tmp_path / "jobs.db").source_intelligence()[0]
    assert metric["fetched"] == 1 and metric["relevant"] == 1
    assert metric["apply_count"] + metric["review_count"] + metric["reject_count"] == 1
    assert 0 <= quality_score(10, 5, 2, 2, 1, 0, 4) <= 100


def test_target_health_after_three_failures():
    target = CompanyTarget("A")
    for _ in range(3): target.register_result("error")
    assert target.health == TargetHealth.DEGRADED
    target.register_result(None); assert target.health == TargetHealth.HEALTHY


def test_priority_freshness_under_72_hours():
    now = datetime(2026, 8, 29, tzinfo=timezone.utc)
    assert is_priority_fresh((now - timedelta(hours=71)).isoformat(), 3, now)
    assert not is_priority_fresh((now - timedelta(hours=73)).isoformat(), 3, now)


def test_preferred_company_bonus_is_small():
    profile = load_profile("config/profile.example.yaml")
    job = Job("Data Analyst", "Other", "Madrid", "onsite", "SQL", "x", "https://x/1")
    normalize_job(job, profile.skills); baseline = score_job(job, profile).score
    preferred = replace(profile, preferred_companies=["Other"])
    bonus = score_job(job, preferred).score - baseline
    assert 0 < bonus < 5


def test_dedup_fingerprint_and_no_false_merge():
    first = raw("https://one.test/1", description="SQL data analytics")
    duplicate = raw("https://two.test/2", description="SQL data analytics")
    different = raw("https://three.test/3", description="SQL data analytics and a distinct product scope")
    result = DiscoveryAggregator([FakeSource("mock", [first, duplicate, different])]).discover("Data Analyst")
    assert len(result.jobs) == 2 and result.stats["mock"].duplicates == 1


def test_target_errors_and_zero_results_do_not_break_run(tmp_path):
    empty = FakeSource("empty", [])
    result = run_discovery_pipeline([BrokenTarget(), empty], "config/profile.example.yaml", tmp_path / "jobs.db",
                                    queries=["Data Analyst"])
    assert result.jobs == [] and "lever:broken" in result.discovery.errors
    rows = JobDatabase(tmp_path / "jobs.db").source_intelligence()
    assert len(rows) == 2 and next(r for r in rows if r["source"] == "empty")["fetched"] == 0


def test_discovery_report_command_and_database_report(tmp_path):
    database = JobDatabase(tmp_path / "jobs.db")
    database.record_source_metric(run_id=None, source="mock", target="mock:a", sector="Retail", fetched=0,
        relevant_by_title=0, relevant_after_description=0, pre_score_rejected=0, scored=0,
        apply_count=0, review_count=0, reject_count=0, duplicates=0, error=None, latency_ms=1,
        fresh_count=0, quality_score=50)
    report = database.discovery_report()
    assert report["targets_without_results"] == ["mock:a"]
    assert build_parser().parse_args(["discovery-report"]).command == "discovery-report"
