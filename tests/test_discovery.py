from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from job_hunter.discovery.aggregator import DiscoveryAggregator, raw_to_job
from job_hunter.discovery.base import JobSource
from job_hunter.discovery.matching import geography_compatible, is_fresh, title_matches
from job_hunter.discovery.models import RawJob
from job_hunter.discovery.sources import (
    ArbeitnowSource, AshbySource, GenericCareersSource, GreenhouseSource, LeverSource,
    RemoteOKSource, WorkableSource,
)
from job_hunter.models import Job
from job_hunter.pipeline import rank_jobs, run_discovery_pipeline


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


def test_greenhouse_mapping():
    source = GreenhouseSource("Acme", "acme", fetcher=lambda _: {"jobs": [{
        "id": 1, "title": "Analista de Datos", "location": {"name": "Buenos Aires"},
        "content": "<p>SQL</p>", "absolute_url": "https://boards.greenhouse.io/acme/1",
        "updated_at": "2026-08-28T10:00:00Z",
    }]})
    job = source.discover("Analista de Datos")[0]
    assert job.company == "Acme"
    assert job.location == "Buenos Aires"
    assert job.published_at == "2026-08-28T10:00:00Z"


def test_lever_mapping():
    source = LeverSource("Acme", "acme", fetcher=lambda _: [{
        "id": "l1", "text": "Business Analyst", "categories": {"location": "Argentina"},
        "descriptionPlain": "SQL", "hostedUrl": "https://jobs.lever.co/acme/l1",
        "workplaceType": "hybrid", "createdAt": 1787900000,
    }])
    job = source.discover("Business Analyst")[0]
    assert job.work_mode == "hybrid"
    assert job.external_id == "l1"


def test_ashby_mapping():
    source = AshbySource("Acme", "acme", fetcher=lambda _: {"jobs": [{
        "id": "a1", "title": "Pricing Analyst", "location": "Remote LATAM",
        "isRemote": True, "isListed": True, "descriptionPlain": "Pricing and Excel",
        "jobUrl": "https://jobs.ashbyhq.com/acme/a1", "publishedAt": "2026-08-27T00:00:00Z",
    }]})
    job = source.discover("Pricing Analyst")[0]
    assert job.work_mode == "remote"
    assert job.location == "Remote LATAM"


def test_remote_latam_is_valid_and_us_only_is_invalid():
    valid = raw(title="Data Analyst")
    valid.location, valid.work_mode = "Remote LATAM", "remote"
    assert geography_compatible(valid, ["Argentina", "Remote LATAM"])[0]
    invalid = raw(title="Data Analyst")
    invalid.location, invalid.description = "Remote", "Candidates must be US only"
    assert not geography_compatible(invalid, ["Argentina", "Remote LATAM"])[0]


def test_incompatible_non_argentina_location_is_rejected():
    job = raw(title="Data Analyst")
    job.location = "Madrid, Spain"
    assert not geography_compatible(job, ["Argentina", "Buenos Aires"])[0]


def test_spanish_title_aliases():
    aliases = ["Analista de Datos", "Analista de Negocios", "Analista Comercial"]
    assert title_matches("Analista de Datos Junior", aliases)
    assert title_matches("Analista Comercial Ssr", aliases)
    assert not title_matches("Ingeniero de Datos", aliases)


def test_freshness_filter():
    now = datetime(2026, 8, 29, tzinfo=timezone.utc)
    assert is_fresh((now - timedelta(days=13)).isoformat(), 14, now)
    assert not is_fresh((now - timedelta(days=15)).isoformat(), 14, now)
    assert is_fresh(None, 14, now)
    recent_milliseconds = int((now - timedelta(days=2)).timestamp() * 1000)
    assert is_fresh(str(recent_milliseconds), 14, now)


def test_ranking_apply_before_review_before_reject():
    apply = Job("A", "C", "Argentina", "hybrid", "", "x", "https://x/a", score=75, decision="APPLY")
    review = Job("B", "C", "Argentina", "hybrid", "", "x", "https://x/b", score=74, decision="REVIEW")
    reject = Job("C", "C", "Argentina", "hybrid", "", "x", "https://x/c", score=99, decision="REJECT")
    assert [job.decision for job in rank_jobs([reject, review, apply])] == ["APPLY", "REVIEW", "REJECT"]


def test_workable_public_mapping():
    source = WorkableSource("Acme", "acme", fetcher=lambda _: {"jobs": [{
        "id": "w1", "title": "Data Analyst", "description": "SQL",
        "location": {"location_str": "Buenos Aires, Argentina", "workplace_type": "hybrid"},
        "url": "https://apply.workable.com/acme/j/w1", "created_at": "2026-08-28T00:00:00Z",
    }]})
    job = source.discover("Data Analyst")[0]
    assert job.location == "Buenos Aires, Argentina"
    assert job.work_mode == "hybrid"


def test_generic_careers_maps_json_ld_job_posting():
    document = '''<script type="application/ld+json">{
      "@type":"JobPosting", "identifier":{"value":"g1"}, "title":"Analista Comercial",
      "description":"Excel", "datePosted":"2026-08-28", "url":"https://careers.example.com/g1",
      "hiringOrganization":{"name":"Acme"},
      "jobLocation":{"address":{"addressLocality":"CABA","addressCountry":"Argentina"}}
    }</script>'''
    source = GenericCareersSource("careers:Acme", "https://careers.example.com", fetcher=lambda _: document)
    job = source.discover("Analista Comercial")[0]
    assert job.company == "Acme"
    assert "Argentina" in job.location
