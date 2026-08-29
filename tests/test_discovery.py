from __future__ import annotations

from dataclasses import dataclass

from job_hunter.discovery.aggregator import DiscoveryAggregator, raw_to_job
from job_hunter.discovery.base import JobSource
from job_hunter.discovery.models import RawJob
from job_hunter.discovery.sources import ArbeitnowSource, RemoteOKSource
from job_hunter.pipeline import run_discovery_pipeline


def raw(
    url: str = "https://example.com/job?utm_source=test",
    title: str = "Pricing Analyst Junior",
    source: str = "fake",
) -> RawJob:
    return RawJob(
        external_id=url,
        title=title,
        company="Acme",
        location="Buenos Aires",
        work_mode="Hybrid",
        description="<p>Excel, SQL y pricing. Inglés intermedio. 1 año de experiencia.</p>",
        source=source,
        url=url,
        published_at="2026-08-29",
    )


@dataclass
class FakeSource(JobSource):
    name: str
    jobs: list[RawJob]

    def discover(self, query, location=None, limit=None):
        return self.jobs[:limit]


class BrokenSource(JobSource):
    name = "broken"

    def discover(self, query, location=None, limit=None):
        raise TimeoutError("source unavailable")


def test_source_failure_does_not_stop_other_sources(caplog):
    result = DiscoveryAggregator([BrokenSource(), FakeSource("working", [raw(source="working")])]).discover(
        "Pricing Analyst"
    )
    assert len(result.jobs) == 1
    assert "TimeoutError" in result.stats["broken"].error
    assert result.stats["working"].accepted == 1


def test_cross_source_deduplication_uses_canonical_url_and_content():
    first = raw(source="one")
    same_url = raw("https://example.com/job?utm_campaign=other", source="two")
    same_content = raw("https://another.example/job", source="two")
    result = DiscoveryAggregator(
        [FakeSource("one", [first]), FakeSource("two", [same_url, same_content])]
    ).discover("Pricing Analyst")
    assert len(result.jobs) == 1
    assert result.stats["two"].duplicates == 2


def test_raw_job_normalization_removes_html_and_tracking():
    job = raw_to_job(raw())
    assert job.description.startswith("Excel")
    assert "<p>" not in job.description
    assert job.url == "https://example.com/job"


def test_discovery_to_scorer_integration(tmp_path):
    result = run_discovery_pipeline(
        [FakeSource("fake", [raw()])],
        "config/profile.example.yaml",
        tmp_path / "jobs.db",
        queries=["Pricing Analyst"],
        limit=5,
    )
    assert result.inserted == 1
    assert result.jobs[0].decision == "APPLY"
    assert result.jobs[0].score >= 75


def test_remoteok_adapter_maps_public_payload_and_reuses_feed():
    calls = []

    def fetcher(url):
        calls.append(url)
        return [
            {"legal": "notice"},
            {
                "id": "42", "position": "Data Analyst", "company": "Remote Co",
                "location": "Worldwide", "description": "SQL data analyst", "tags": ["data"],
                "url": "https://remoteok.com/42", "date": "2026-08-29",
            },
        ]

    source = RemoteOKSource(fetcher=fetcher)
    assert source.discover("Data Analyst", limit=1)[0].work_mode == "remote"
    source.discover("Analyst", limit=1)
    assert len(calls) == 1


def test_arbeitnow_adapter_maps_public_payload():
    source = ArbeitnowSource(fetcher=lambda _: {
        "data": [{
            "slug": "business-analyst-acme", "title": "Business Analyst", "company_name": "Acme",
            "location": "Berlin", "remote": True, "description": "Business analysis and SQL",
            "tags": ["analytics"], "created_at": 1788000000,
        }]
    })
    job = source.discover("Business Analyst", limit=1)[0]
    assert job.company == "Acme"
    assert job.url.endswith("business-analyst-acme")
    assert job.work_mode == "remote"
