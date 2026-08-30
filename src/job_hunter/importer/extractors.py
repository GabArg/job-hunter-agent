from __future__ import annotations

import html
import json
import re
from html.parser import HTMLParser
from typing import Any

from ..normalizer import normalize_work_mode
from .models import ExtractedJob


def extract_job(document: str, url: str) -> tuple[ExtractedJob, str]:
    structured = extract_json_ld(document, url)
    if structured:
        return structured, "JSON_LD"
    parser = JobHTMLParser(); parser.feed(document or "")
    title = parser.meta.get("og:title") or parser.meta.get("twitter:title") or parser.heading or parser.title
    company = parser.meta.get("og:site_name") or parser.meta.get("author") or ""
    description = parser.main_text or parser.meta.get("description") or parser.meta.get("og:description") or ""
    location = parser.meta.get("job:location") or parser.meta.get("location") or ""
    title = _clean_title(title, company)
    return ExtractedJob(title, company, location, normalize_work_mode(None, description), sanitize_html(description), url=url), "LIGHT_HTML"


def extract_json_ld(document: str, url: str) -> ExtractedJob | None:
    scripts = re.findall(r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
                         document or "", flags=re.I | re.S)
    for script in scripts:
        try: payload = json.loads(html.unescape(script).strip())
        except (json.JSONDecodeError, TypeError): continue
        values = payload if isinstance(payload, list) else payload.get("@graph", [payload]) if isinstance(payload, dict) else []
        for item in values:
            types = item.get("@type", []) if isinstance(item, dict) else []
            if isinstance(types, str): types = [types]
            if "JobPosting" not in types: continue
            org = item.get("hiringOrganization") or {}; company = org.get("name", "") if isinstance(org, dict) else str(org)
            location = _jsonld_location(item.get("jobLocation") or item.get("applicantLocationRequirements"))
            description = sanitize_html(str(item.get("description") or ""))
            employment = item.get("jobLocationType") or ""
            return ExtractedJob(str(item.get("title") or item.get("name") or ""), company, location,
                normalize_work_mode(employment, description, item), description,
                str(item.get("datePosted") or "") or None, str(item.get("url") or url))
    return None


class JobHTMLParser(HTMLParser):
    def __init__(self):
        super().__init__(); self.meta: dict[str, str] = {}; self.title = ""; self.heading = ""
        self._tag = ""; self._skip = 0; self._main = 0; self._content: list[str] = []

    @property
    def main_text(self) -> str: return " ".join(self._content).strip()

    def handle_starttag(self, tag, attrs):
        values = dict(attrs); self._tag = tag
        if tag in {"script", "style", "noscript"}: self._skip += 1
        if tag in {"main", "article"}: self._main += 1
        if tag == "meta":
            key = values.get("property") or values.get("name") or values.get("itemprop")
            if key and values.get("content"): self.meta[key.casefold()] = values["content"]

    def handle_endtag(self, tag):
        if tag in {"script", "style", "noscript"} and self._skip: self._skip -= 1
        if tag in {"main", "article"} and self._main: self._main -= 1
        self._tag = ""

    def handle_data(self, data):
        if self._skip or not data.strip(): return
        if self._tag == "title": self.title += " " + data.strip()
        elif self._tag == "h1" and not self.heading: self.heading = data.strip()
        if self._main: self._content.append(data.strip())


def sanitize_html(value: str) -> str:
    parser = _TextParser(); parser.feed(value or "")
    return re.sub(r"\s+", " ", html.unescape(" ".join(parser.text))).strip()


class _TextParser(HTMLParser):
    def __init__(self): super().__init__(); self.text: list[str] = []; self.skip = 0
    def handle_starttag(self, tag, attrs):
        if tag in {"script", "style", "noscript"}: self.skip += 1
    def handle_endtag(self, tag):
        if tag in {"script", "style", "noscript"} and self.skip: self.skip -= 1
    def handle_data(self, data):
        if not self.skip and data.strip(): self.text.append(data.strip())


def _jsonld_location(value: Any) -> str:
    values = value if isinstance(value, list) else [value]
    parts: list[str] = []
    for entry in values:
        if not isinstance(entry, dict): continue
        address = entry.get("address") or entry
        if isinstance(address, dict):
            parts.append(", ".join(str(address.get(k)) for k in ("addressLocality", "addressRegion", "addressCountry", "name") if address.get(k)))
    return "; ".join(part for part in parts if part)


def _clean_title(value: str, company: str) -> str:
    title = re.sub(r"\s+", " ", value or "").strip()
    if company and title.casefold().endswith(f" | {company}".casefold()): title = title[:-(len(company) + 3)]
    return title
