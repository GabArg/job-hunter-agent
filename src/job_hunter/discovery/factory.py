from __future__ import annotations

from urllib.parse import urlsplit

from ..models import Profile
from .base import JobSource, fetch_text
from .sources import (
    ArbeitnowSource, AshbySource, GenericCareersSource, GreenhouseSource,
    LeverSource, RemoteOKSource, WorkableSource,
)
from .target_registry import TargetRegistry

ATS_FACTORIES = {
    "greenhouse": GreenhouseSource,
    "lever": LeverSource,
    "ashby": AshbySource,
    "workable": WorkableSource,
}


def build_sources(profile: Profile, selected: list[str] | None = None) -> list[JobSource]:
    selected_set = set(selected or [])
    include_all = not selected_set
    sources: list[JobSource] = []
    if include_all or "remoteok" in selected_set: sources.append(RemoteOKSource())
    if include_all or "arbeitnow" in selected_set: sources.append(ArbeitnowSource())
    mapping = {"discovery_targets": profile.discovery_targets, "career_pages": profile.career_pages, "career_targets": profile.career_targets}
    for target in TargetRegistry.from_mapping(mapping).active:
        company, ats = target.company, target.source_type
        if not company: raise ValueError("Every discovery target requires company")
        if not include_all and ats not in selected_set: continue
        if ats in ATS_FACTORIES:
            token = target.token or _token_from_url(target.url)
            if not token: raise ValueError(f"Discovery target {company} requires token/account")
            source = ATS_FACTORIES[ats](company, token)
        else:
            source = GenericCareersSource(f"careers:{company}", target.url, fetcher=fetch_text)
        source.sector, source.sector_confidence = target.sector, 1.0
        source.target_priority, source.target_id = target.priority, target.id
        sources.append(source)
    return sources


def _infer_ats(url: str) -> str:
    host = urlsplit(url).netloc.lower()
    return next((ats for marker, ats in {
        "greenhouse.io": "greenhouse", "lever.co": "lever", "ashbyhq.com": "ashby",
        "workable.com": "workable",
    }.items() if marker in host), "generic")


def _token_from_url(url: str) -> str:
    parts = [part for part in urlsplit(url).path.split("/") if part]
    return parts[-1] if parts else ""
