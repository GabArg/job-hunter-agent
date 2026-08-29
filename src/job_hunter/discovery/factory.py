from __future__ import annotations

from urllib.parse import urlsplit

from ..models import Profile
from .base import JobSource, fetch_text
from .sources import (
    ArbeitnowSource, AshbySource, GenericCareersSource, GreenhouseSource,
    LeverSource, RemoteOKSource, WorkableSource,
)

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
    for target in profile.career_targets:
        company = str(target.get("company") or "").strip()
        ats = str(target.get("ats") or _infer_ats(str(target.get("careers_url") or ""))).lower()
        if not company:
            raise ValueError("Every career target requires company")
        if not include_all and ats not in selected_set: continue
        if ats in ATS_FACTORIES:
            token = str(target.get("board_token") or _token_from_url(str(target.get("careers_url") or ""))).strip()
            if not token: raise ValueError(f"Career target {company} requires board_token")
            sources.append(ATS_FACTORIES[ats](company, token))
        elif ats in {"generic", "careers"}:
            url = str(target.get("careers_url") or "")
            sources.append(GenericCareersSource(f"careers:{company}", url, fetcher=fetch_text))
        else:
            raise ValueError(f"Unsupported ATS '{ats}' for {company}")
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
