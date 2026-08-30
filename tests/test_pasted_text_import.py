from __future__ import annotations

from pathlib import Path

import pytest

from job_hunter.config import load_profile
from job_hunter.database import JobDatabase
from job_hunter.importer import ImportStatus, import_manual_job, is_internal_job_url


PROFILE = load_profile("config/profile.example.yaml")
DESCRIPTION = """Buscamos Asistente BI para elaboración de reportes y tableros.
Enviar CV a reclutamiento@yccsolutions.com
Asunto: Asistente BI – Referencia: REC 004 - 2026
Se valoran Excel, Power BI y análisis de información."""
INFOTREE_DESCRIPTION = """Si cumples con el perfil y te interesa esta oportunidad,
envía tu CV en inglés a amesen@infotreeservice.com."""


def data(**changes):
    value = {"company": "ProPremix", "title": "Asistente BI", "description": DESCRIPTION}
    value.update(changes); return value


@pytest.mark.parametrize("method", ["PASTED_TEXT", "MANUAL_FORM"])
def test_text_or_manual_without_url_imports(tmp_path, method):
    database = JobDatabase(tmp_path / "jobs.db")
    result = import_manual_job(data(), PROFILE, database, method=method)
    row = database.get_job_row(result.job_id)
    assert result.status == ImportStatus.IMPORTED and is_internal_job_url(row["url"])
    assert row["import_method"] == method
    assert row["source"] == ("manual:text" if method == "PASTED_TEXT" else "manual:user")


@pytest.mark.parametrize(("missing", "label"), [
    ("company", "empresa"), ("title", "puesto"), ("description", "descripción"),
])
def test_required_manual_fields(tmp_path, missing, label):
    database = JobDatabase(tmp_path / "jobs.db"); payload = data(**{missing: ""})
    result = import_manual_job(payload, PROFILE, database, method="PASTED_TEXT")
    assert result.status == ImportStatus.NEEDS_MANUAL_INPUT and label in result.warnings[0]
    assert database.list_jobs() == []


def test_email_and_required_subject_without_url(tmp_path):
    database = JobDatabase(tmp_path / "jobs.db")
    result = import_manual_job(data(), PROFILE, database, method="PASTED_TEXT")
    row = database.get_job_row(result.job_id)
    assert row["application_method"] == "EMAIL"
    assert row["application_email"] == "reclutamiento@yccsolutions.com"
    assert row["email_subject"] == "Asistente BI – Referencia: REC 004 - 2026"


def test_infotree_pasted_text_detects_email_and_english_cv_instruction(tmp_path):
    database = JobDatabase(tmp_path / "jobs.db")
    result = import_manual_job({
        "company": "InfoTree Service", "title": "Data Analyst", "description": INFOTREE_DESCRIPTION,
    }, PROFILE, database, method="PASTED_TEXT")
    row = database.get_job_row(result.job_id)
    assert row["application_method"] == "EMAIL"
    assert row["application_email"] == "amesen@infotreeservice.com"
    assert "CV en inglés" in row["application_instructions"]


def test_no_url_deduplicates_by_stable_fingerprint(tmp_path):
    database = JobDatabase(tmp_path / "jobs.db")
    first = import_manual_job(data(), PROFILE, database, method="PASTED_TEXT")
    second = import_manual_job(data(), PROFILE, database, method="PASTED_TEXT")
    assert first.status == ImportStatus.IMPORTED and second.status == ImportStatus.DUPLICATE
    assert first.job_id == second.duplicate_job_id and len(database.list_jobs()) == 1
    assert database.get_job_row(first.job_id)["url"].startswith("manual://")


def test_internal_url_is_not_exposed_as_dashboard_link():
    source = Path("app/streamlit_app.py").read_text(encoding="utf-8")
    assert is_internal_job_url("manual://abc") and is_internal_job_url("https://manual.invalid/legacy")
    assert 'if is_internal_job_url(str(row["url"]))' in source
    assert "Sin URL pública" in source


def test_manual_form_submit_is_not_dynamically_disabled():
    source = Path("app/streamlit_app.py").read_text(encoding="utf-8")
    assert 'save_manual = st.form_submit_button("Guardar y analizar")' in source
    assert 'form_submit_button("Guardar y analizar", disabled=' not in source
    assert 'st.error("Faltan campos obligatorios: " + ", ".join(missing_manual))' in source


def test_adding_real_url_promotes_existing_job_without_duplicate(tmp_path):
    database = JobDatabase(tmp_path / "jobs.db")
    first = import_manual_job(data(), PROFILE, database, method="PASTED_TEXT")
    public_url = "https://careers.propremix.example/jobs/asistente-bi"
    second = import_manual_job(data(url=public_url), PROFILE, database, method="PASTED_TEXT")
    row = database.get_job_row(first.job_id)
    assert second.status == ImportStatus.DUPLICATE and second.duplicate_job_id == first.job_id
    assert len(database.list_jobs()) == 1 and row["url"] == public_url
    assert row["import_source_url"] == public_url


def test_legacy_url_manual_import_still_works(tmp_path):
    database = JobDatabase(tmp_path / "jobs.db")
    result = import_manual_job(data(url="https://example.com/jobs/bi"), PROFILE, database)
    assert result.status == ImportStatus.IMPORTED
    assert database.get_job_row(result.job_id)["url"] == "https://example.com/jobs/bi"
