from pathlib import Path


SOURCE = Path("app/streamlit_app.py").read_text(encoding="utf-8")


def test_dashboard_separates_technical_match_from_eligibility():
    assert '_metric_card("Match técnico"' in SOURCE
    assert '_metric_card("Elegibilidad"' in SOURCE
    assert 'Motivo principal:' in SOURCE


def test_metric_cards_have_dark_high_contrast_classes():
    for class_name in ("jh-card", "jh-card-label", "jh-card-value", "jh-card-match", "jh-card-reject"):
        assert class_name in SOURCE
    assert "background:#151c28" in SOURCE
    assert "color:#f7f9fc" in SOURCE
    assert ".stMetric {background:#fff" not in SOURCE


def test_job_detail_has_clear_tabs_and_factual_evidence():
    assert '["Resumen", "Match", "Postulación", "CV / Email", "Descripción", "Debug"]' in SOURCE
    assert 'matched_requirement_evidence' in SOURCE
    assert 'Evidencia factual del match' in SOURCE


def test_job_list_has_requested_filters():
    for label in ("Decisión", "Estado operativo", "Modalidad", "Sector", "Canal"):
        assert f'"{label}"' in SOURCE


def test_primary_job_table_is_compact():
    table_block = SOURCE[SOURCE.index('decision_icons ='):SOURCE.index('choices = {')]
    for column in ("Puesto", "Empresa", "Score", "Decisión", "Estado", "Modalidad", "Canal", "Fecha"):
        assert f'"{column}"' in table_block
    for secondary in ("Ubicación", "Fuente", "Sector", "Oferta"):
        assert f'"{secondary}"' not in table_block


def test_table_score_is_presented_as_percentage():
    assert '"Score": f\'{float(row.get("score") or 0):.0f}%\'' in SOURCE


def test_ui_translation_maps_cover_internal_states():
    expected = (
        '"APPLY": "Aplicar"', '"REVIEW": "Revisar"', '"REJECT": "Rechazar"',
        '"NEW": "Nuevo"', '"SHORTLISTED": "Preseleccionado"', '"CV_GENERATED": "CV generado"',
        '"APPROVED_TO_APPLY": "Aprobado para postular"', '"APPLIED": "Postulado"', '"SKIPPED": "Descartado"',
        '"remote": "Remoto"', '"hybrid": "Híbrido"', '"onsite": "Presencial"', '"unknown": "No informado"',
        '"EMAIL": "Email"', '"LINK": "Link"', '"LINK_EMAIL": "Link + Email"', '"UNKNOWN": "No detectado"',
    )
    assert all(value in SOURCE for value in expected)


def test_friendly_filters_keep_internal_values():
    assert '["ALL", "APPLY", "REVIEW", "REJECT"]' in SOURCE
    assert '["ALL", "remote", "hybrid", "onsite", "unknown"]' in SOURCE
    assert '["ALL", "EMAIL", "LINK", "LINK_EMAIL", "UNKNOWN"]' in SOURCE
    assert 'row.get("decision") == selected_decision' in SOURCE
    assert 'row.get("application_status") == selected_status' in SOURCE


def test_sidebar_uses_advanced_configuration_expander():
    assert 'st.expander("Configuración avanzada", expanded=False)' in SOURCE


def test_raw_json_is_only_rendered_in_technical_expanders():
    json_lines = [line.strip() for line in SOURCE.splitlines() if "st.json(" in line]
    assert json_lines
    assert all("expander" in line and ("técnic" in line or "Cambios propuestos" in line) for line in json_lines)


def test_dashboard_keeps_core_actions():
    for label in ("Generar CV", "Ver HTML", "Descargar PDF", "Preparar email", "Aprobar email",
                  "Crear borrador en Gmail", "Marcar como postulada por link", "Descartar"):
        assert label in SOURCE
    assert 'st.markdown("#### Acciones")' in SOURCE
    assert '"🗑️ Descartar", key=f"skip-{job_id}", type="secondary"' in SOURCE
