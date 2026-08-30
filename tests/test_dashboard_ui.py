from pathlib import Path


SOURCE = Path("app/streamlit_app.py").read_text(encoding="utf-8")


def test_dashboard_separates_technical_match_from_eligibility():
    assert 'metric("Match técnico"' in SOURCE
    assert 'metric("Elegibilidad"' in SOURCE
    assert 'Motivo principal:' in SOURCE


def test_job_detail_has_clear_tabs_and_factual_evidence():
    assert '["Resumen", "Match", "Postulación", "CV / Email", "Descripción", "Debug"]' in SOURCE
    assert 'matched_requirement_evidence' in SOURCE
    assert 'Evidencia factual del match' in SOURCE


def test_job_list_has_requested_filters():
    for label in ("Decisión", "Estado operativo", "Modalidad", "Sector", "Canal"):
        assert f'selectbox("{label}"' in SOURCE


def test_raw_json_is_only_rendered_in_technical_expanders():
    json_lines = [line.strip() for line in SOURCE.splitlines() if "st.json(" in line]
    assert json_lines
    assert all("expander" in line and ("técnic" in line or "Cambios propuestos" in line) for line in json_lines)


def test_dashboard_keeps_core_actions():
    for label in ("Generar CV", "Ver HTML", "Descargar PDF", "Preparar email", "Aprobar email",
                  "Crear borrador en Gmail", "Marcar como postulada por link", "Descartar"):
        assert label in SOURCE
