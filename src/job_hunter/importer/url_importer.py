from __future__ import annotations

import ipaddress
import re
import socket
from datetime import datetime, timezone
from urllib.error import HTTPError
from urllib.parse import urljoin, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

from ..database import JobDatabase
from ..discovery.aggregator import canonical_url
from ..models import Job, Profile
from ..normalizer import normalize_work_mode
from ..pipeline import process_job
from .extractors import extract_job, sanitize_html
from .models import ExtractedJob, ImportResult, ImportStatus

SOURCE_HOSTS = {
    "linkedin.com": "linkedin", "greenhouse.io": "greenhouse", "lever.co": "lever",
    "ashbyhq.com": "ashby", "workable.com": "workable", "smartrecruiters.com": "smartrecruiters",
    "recruitee.com": "recruitee",
}


def detect_source_type(url: str) -> str:
    parts = urlsplit(url)
    host = (parts.hostname or "").casefold()
    known = next((source for marker, source in SOURCE_HOSTS.items()
                  if host == marker or host.endswith("." + marker)), None)
    if known:
        return known
    path = parts.path.casefold()
    markers = ("/job", "/jobs", "/career", "/careers", "/empleo", "/vacante")
    return "generic" if any(marker in path for marker in markers) else "unknown"


def validate_public_url(url: str, resolver=socket.getaddrinfo) -> str:
    parts = urlsplit((url or "").strip())
    if parts.scheme not in {"http", "https"} or not parts.hostname:
        raise ValueError("La URL debe usar http o https")
    host = parts.hostname.casefold()
    if host == "localhost" or host.endswith(".localhost"):
        raise ValueError("Host local bloqueado")
    try:
        literal = ipaddress.ip_address(host)
        addresses = [literal]
    except ValueError:
        addresses = [ipaddress.ip_address(item[4][0]) for item in resolver(host, parts.port or (443 if parts.scheme == "https" else 80), type=socket.SOCK_STREAM)]
    if not addresses or any(address.is_private or address.is_loopback or address.is_link_local or address.is_reserved or address.is_multicast for address in addresses):
        raise ValueError("Dirección privada o interna bloqueada")
    return parts.geturl()


class SafeHTTPClient:
    def __init__(self, timeout: float = 15, max_redirects: int = 5, max_response_size: int = 2_000_000,
                 resolver=socket.getaddrinfo):
        self.timeout, self.max_response_size, self.resolver = timeout, max_response_size, resolver
        self.opener = build_opener(_SafeRedirect(max_redirects, resolver))

    def fetch(self, url: str) -> tuple[str, str]:
        validate_public_url(url, self.resolver)
        request = Request(url, headers={"User-Agent": "JobHunterAgent/0.4 manual URL import", "Accept": "text/html,application/xhtml+xml"})
        with self.opener.open(request, timeout=self.timeout) as response:
            content_type = response.headers.get_content_type()
            if content_type not in {"text/html", "application/xhtml+xml", "application/ld+json"}:
                raise ValueError("La respuesta no es HTML")
            declared = int(response.headers.get("Content-Length") or 0)
            if declared > self.max_response_size: raise ValueError("La respuesta excede el tamaño permitido")
            body = response.read(self.max_response_size + 1)
            if len(body) > self.max_response_size: raise ValueError("La respuesta excede el tamaño permitido")
            return response.geturl(), body.decode(response.headers.get_content_charset() or "utf-8", errors="replace")


class _SafeRedirect(HTTPRedirectHandler):
    def __init__(self, maximum: int, resolver): super().__init__(); self.maximum, self.resolver = maximum, resolver
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        # urllib title-cases custom headers inconsistently; get_header performs
        # its canonical lookup and also covers headers added after creation.
        count = int(req.get_header("X-jobhunter-redirects", "0")) + 1
        if count > self.maximum: raise HTTPError(newurl, 310, "Demasiadas redirecciones", headers, fp)
        target = urljoin(req.full_url, newurl); validate_public_url(target, self.resolver)
        redirected = super().redirect_request(req, fp, code, msg, headers, target)
        if redirected: redirected.add_header("X-JobHunter-Redirects", str(count))
        return redirected


def import_job_from_url(url: str, profile: Profile, database: JobDatabase, *, fetcher=None) -> ImportResult:
    try: validated = validate_public_url(url) if fetcher is None else _basic_validate(url)
    except Exception as exc: return _record_failure(database, url, "unknown", ImportStatus.UNSUPPORTED, str(exc))
    source_type = detect_source_type(validated); canonical = canonical_url(validated)
    try:
        final_url, document = (fetcher or SafeHTTPClient().fetch)(validated)
        canonical = canonical_url(final_url); source_type = detect_source_type(final_url)
        extracted, method = extract_job(document, canonical)
        if source_type == "unknown" and (extracted.title or extracted.description):
            source_type = "generic"
    except Exception as exc:
        warning = _friendly_network_error(exc, source_type)
        status = ImportStatus.NEEDS_MANUAL_INPUT if source_type == "linkedin" else ImportStatus.FAILED
        return _record_failure(database, canonical, source_type, status, warning)
    return _persist_extracted(extracted, profile, database, source_type, canonical, method, "PUBLIC_URL")


def import_manual_job(data: dict, profile: Profile, database: JobDatabase, *, method: str = "MANUAL_FORM") -> ImportResult:
    url = str(data.get("url") or "").strip() or f"https://manual.invalid/{datetime.now(timezone.utc).timestamp()}"
    if not url.startswith("https://manual.invalid"):
        try: _basic_validate(url)
        except ValueError as exc: return _record_failure(database, url, "user", ImportStatus.UNSUPPORTED, str(exc), method)
    raw_description = str(data.get("description") or "")
    description = sanitize_html(raw_description)
    title, company, location = _infer_manual_fields(raw_description, str(data.get("title") or ""),
                                                     str(data.get("company") or ""), str(data.get("location") or ""))
    extracted = ExtractedJob(title, company, location,
        normalize_work_mode(data.get("work_mode"), description), description,
        str(data.get("published_at") or "") or None, url)
    return _persist_extracted(extracted, profile, database, "user", canonical_url(url), method, method)


def _persist_extracted(extracted: ExtractedJob, profile: Profile, database: JobDatabase, source_type: str,
                       canonical: str, extraction_method: str, import_method: str) -> ImportResult:
    missing = [name for name, value in (("puesto", extracted.title), ("empresa", extracted.company), ("descripción", extracted.description)) if not value.strip()]
    if missing:
        warning = "Faltan datos obligatorios: " + ", ".join(missing)
        return _record_failure(database, canonical, source_type, ImportStatus.NEEDS_MANUAL_INPUT, warning, import_method,
                               extracted.title, extracted.company, extraction_method)
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    job = Job(extracted.title, extracted.company, extracted.location, extracted.work_mode, extracted.description,
              f"manual:{source_type}", canonical, published_at=extracted.published_at, imported_manually=True,
              imported_at=now, import_source_url=canonical, import_method=import_method)
    duplicate = database.find_duplicate_job(job, extracted.url)
    if duplicate:
        result = ImportResult(ImportStatus.DUPLICATE, source_type, canonical, job.title, job.company, job.location,
            job.work_mode, job.description, job.published_at, duplicate_job_id=int(duplicate["id"]),
            job_id=int(duplicate["id"]), extraction_method=extraction_method, decision=duplicate["decision"],
            score=duplicate["score"], sector=duplicate.get("sector") or "Other")
        database.record_import(source_url=canonical, company=job.company, title=job.title, source_type=source_type,
            result=result.status.value, duplicate_job_id=result.duplicate_job_id, import_method=import_method)
        return result
    process_job(job, profile, database)
    stored = database.get_job(None, job.url); job_id = stored.id if stored else None
    result = ImportResult(ImportStatus.IMPORTED, source_type, canonical, job.title, job.company, job.location,
        job.work_mode, job.description, job.published_at, job.application_method, job_id=job_id,
        extraction_method=extraction_method, decision=job.decision, score=job.score, sector=job.sector, reasons=job.reasons)
    database.record_import(source_url=canonical, company=job.company, title=job.title, source_type=source_type,
        result=result.status.value, job_id=job_id, import_method=import_method)
    return result


def _record_failure(database, url, source_type, status, warning, method="PUBLIC_URL", title="", company="", extraction_method=""):
    result = ImportResult(status, source_type, canonical_url(url) if "://" in url else url,
                          title=title, company=company, warnings=[warning], extraction_method=extraction_method)
    database.record_import(source_url=url, company=company, title=title, source_type=source_type,
        result=status.value, warnings=result.warnings, import_method=method)
    return result


def _basic_validate(url: str) -> str:
    parts = urlsplit(url)
    if parts.scheme not in {"http", "https"} or not parts.hostname: raise ValueError("La URL debe usar http o https")
    if parts.hostname.casefold() == "localhost" or parts.hostname.startswith("127."): raise ValueError("Host local bloqueado")
    try:
        address = ipaddress.ip_address(parts.hostname)
        if address.is_private or address.is_loopback or address.is_link_local: raise ValueError("Dirección privada o interna bloqueada")
    except ValueError as exc:
        if "bloqueada" in str(exc): raise
    return url


def _friendly_network_error(exc: Exception, source_type: str) -> str:
    if source_type == "linkedin": return "LinkedIn no expuso suficiente información pública. Pegá el texto de la vacante y la analizamos igual."
    if isinstance(exc, HTTPError): return f"La página respondió HTTP {exc.code}."
    return "No se pudo extraer la vacante de forma segura: " + str(exc)


def _infer_manual_fields(text: str, title: str, company: str, location: str) -> tuple[str, str, str]:
    lines = [line.strip() for line in re.split(r"[\r\n]+", text) if line.strip()]
    if not title and lines and len(lines[0]) <= 120: title = lines[0]
    patterns = (("company", r"(?:empresa|company)\s*:\s*([^\n|]+)"),
                ("location", r"(?:ubicaci[oó]n|location)\s*:\s*([^\n|]+)"))
    for field, pattern in patterns:
        match = re.search(pattern, text, flags=re.I)
        if field == "company" and not company and match: company = match.group(1).strip()
        if field == "location" and not location and match: location = match.group(1).strip()
    return title, company, location
