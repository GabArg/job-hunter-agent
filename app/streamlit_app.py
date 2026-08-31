from __future__ import annotations

import json
import time
from html import escape
from datetime import datetime
from pathlib import Path

import streamlit as st

from job_hunter.config import load_profile
from job_hunter.database import JobDatabase
from job_hunter.discovery.factory import build_sources
from job_hunter.discovery.lock import DiscoveryAlreadyRunning, DiscoveryLock
from job_hunter.knowledge import KnowledgeUpdater
from job_hunter.operations import generate_job_cv, next_schedule_time, prepare_application_email
from job_hunter.application import EmailDraft, GmailEmailProvider, create_approved_gmail_draft
from job_hunter.pipeline import run_discovery_pipeline
from job_hunter.discovery.matching import parse_datetime
from job_hunter.scorer import normalize_reason_list
from job_hunter.semantics import display_concepts
from job_hunter.normalizer import normalize_work_mode
from job_hunter.origin import (AUTOMATIC_DISCOVERY, MANUAL_ORIGINS, UNKNOWN, get_job_origin,
                               filter_jobs_by_origin, origin_label, origin_summary, was_discovered_automatically)
from job_hunter.tracking import ACTIVE_STAGES, CLOSED_STAGES, analytics_snapshot, tracking_row
from job_hunter.importer import (ImportStatus, import_job_from_url, import_manual_job,
                                 is_internal_job_url)


def _display_time(value) -> str:
    if not value: return "—"
    parsed = parse_datetime(value)
    return parsed.astimezone().strftime("%d/%m/%Y %H:%M") if parsed else str(value)


def _display_work_mode(value, description: str = "") -> str:
    return WORK_MODE_LABELS[normalize_work_mode(value, description)]


def _compact_source(value) -> str:
    source = str(value or "—")
    if source.startswith(("http://", "https://")):
        from urllib.parse import urlsplit
        return urlsplit(source).hostname or "web"
    return source if len(source) <= 34 else source[:31] + "…"


BADGE_ICONS = {
    "APPLY": "✅", "REVIEW": "🟡", "REJECT": "🔴", "NEW": "🆕",
    "SHORTLISTED": "⭐", "CV_GENERATED": "📄", "APPROVED_TO_APPLY": "👍",
    "APPLIED": "🚀", "SKIPPED": "⏭️", "LINK": "🔗", "EMAIL": "✉️",
    "LINK_EMAIL": "🔗 + ✉️", "UNKNOWN": "❔", "REMOTE": "🏠",
    "HYBRID": "🔄", "ONSITE": "🏢", "PDF_VALID": "✅", "PDF_INVALID": "⚠️",
}
DECISION_LABELS = {"APPLY": "Aplicar", "REVIEW": "Revisar", "REJECT": "Rechazar"}
STATUS_LABELS = {
    "NEW": "Nuevo", "SHORTLISTED": "Preseleccionado", "CV_GENERATED": "CV generado",
    "APPROVED_TO_APPLY": "Aprobado para postular", "APPLIED": "Postulado", "SKIPPED": "Descartado",
}
WORK_MODE_LABELS = {"remote": "Remoto", "hybrid": "Híbrido", "onsite": "Presencial", "unknown": "No informado"}
METHOD_LABELS = {"EMAIL": "Email", "LINK": "Link", "LINK_EMAIL": "Link + Email", "UNKNOWN": "No detectado"}
STAGE_LABELS = {
    "NOT_APPLIED": "No postulado", "APPLIED": "Postulado", "RECRUITER_VIEWED": "Visto por recruiter",
    "RECRUITER_CONTACT": "Contacto recruiter", "HR_INTERVIEW": "Entrevista RRHH",
    "TECH_INTERVIEW": "Entrevista técnica", "BUSINESS_INTERVIEW": "Entrevista con negocio",
    "FINAL_INTERVIEW": "Entrevista final", "ASSESSMENT": "Assessment / challenge", "OFFER": "Oferta",
    "HIRED": "Contratado", "REJECTED": "Rechazado", "WITHDRAWN": "Retirado",
    "CLOSED_NO_RESPONSE": "Cerrado sin respuesta",
}


def _display_decision(value) -> str:
    return DECISION_LABELS.get(str(value or "").upper(), str(value or "—"))


def _display_status(value) -> str:
    return STATUS_LABELS.get(str(value or "NEW").upper(), str(value or "—").replace("_", " ").title())


def _display_method(value) -> str:
    return METHOD_LABELS.get(str(value or "UNKNOWN").upper(), str(value or "—"))


def _stage_tone(stage: str) -> str:
    if stage in {"REJECTED", "CLOSED_NO_RESPONSE"}: return "stage-rejected"
    if stage in {"HIRED"}: return "stage-hired"
    if stage in {"OFFER"}: return "stage-offer"
    if stage in {"HR_INTERVIEW", "TECH_INTERVIEW", "BUSINESS_INTERVIEW", "FINAL_INTERVIEW", "ASSESSMENT"}: return "stage-interview"
    if stage in {"RECRUITER_VIEWED", "RECRUITER_CONTACT"}: return "stage-response"
    return "status"


def _badge(value, kind: str = "neutral") -> str:
    normalized = str(value or "UNKNOWN").upper()
    label = DECISION_LABELS.get(normalized) or STATUS_LABELS.get(normalized) or METHOD_LABELS.get(normalized)
    if not label:
        mode_key = normalized.casefold()
        label = WORK_MODE_LABELS.get(mode_key, normalized.replace("_", " ").title())
    return f'<span class="jh-badge jh-{kind}">{BADGE_ICONS.get(normalized, "•")} {escape(label)}</span>'


def _origin_badge(row: dict) -> str:
    origin = get_job_origin(row)
    icon = "🔎" if origin == AUTOMATIC_DISCOVERY else "📥" if origin in MANUAL_ORIGINS else "❔"
    kind = "origin-auto" if origin == AUTOMATIC_DISCOVERY else "origin-manual" if origin in MANUAL_ORIGINS else "origin-unknown"
    return f'<span class="jh-badge jh-{kind}">{icon} {escape(origin_label(origin))}</span>'


def _badge_row(*values: tuple[object, str]) -> None:
    st.markdown(" ".join(_badge(value, kind) for value, kind in values), unsafe_allow_html=True)


def _metric_card(label: str, value, tone: str = "neutral", compact: bool = False, note: str = "") -> str:
    size = " jh-card-compact" if compact else ""
    note_html = f'<div class="jh-card-note">{escape(note)}</div>' if note else ""
    return (f'<div class="jh-card jh-card-{tone}{size}"><div class="jh-card-label">{escape(label)}</div>'
            f'<div class="jh-card-value">{escape(str(value))}</div>{note_html}</div>')


def _render_items(title: str, values, empty: str = "Ninguno") -> None:
    st.markdown(f"**{title}**")
    items = list(values or [])
    if not items:
        st.caption(empty)
        return
    st.markdown("".join(f'<span class="jh-chip">{escape(str(item))}</span>' for item in items), unsafe_allow_html=True)


def _reasons(row: dict) -> dict:
    value = row.get("reasons") or {}
    if isinstance(value, dict): return value
    try: return json.loads(str(value))
    except (TypeError, ValueError, json.JSONDecodeError): return {}


def _cv_paths(row: dict) -> tuple[Path, Path]:
    """Resolve persisted professional paths while preserving legacy CV access."""
    job_id = int(row["id"])
    stored = Path(str(row.get("cv_pdf_path") or ""))
    pdf_path = stored if str(stored) not in {"", "."} else Path("outputs/cvs") / str(job_id) / "cv.pdf"
    return pdf_path.with_suffix(".html"), pdf_path


def _render_job_detail(database: JobDatabase, row: dict, master_cv_path: str) -> None:
    reasons = _reasons(row)
    job_id, status = int(row["id"]), str(row["application_status"])
    st.markdown(f"### {escape(str(row['title']))}")
    st.markdown(f"#### {escape(str(row['company']))}")
    _badge_row((row["decision"], str(row["decision"]).lower()),
               (status, "status"), (row.get("application_method"), "channel"),
               (_display_work_mode(row["work_mode"], row["description"]), "mode"))
    st.markdown(_origin_badge(row), unsafe_allow_html=True)
    if get_job_origin(row) in MANUAL_ORIGINS and was_discovered_automatically(row):
        st.caption("Importada inicialmente por el usuario y encontrada posteriormente por discovery.")
    metadata = st.columns(4)
    metadata[0].caption(f"📍 {row.get('location') or 'Ubicación no informada'}")
    metadata[1].caption(f"🏷️ {row.get('sector') or 'Other'}")
    metadata[2].caption(f"🌐 {_compact_source(row.get('source'))}")
    metadata[3].caption(f"📅 {_display_time(row.get('published_at'))}")

    technical, eligibility = st.columns(2)
    technical.markdown(_metric_card("Match técnico", f"{float(row.get('score') or 0):.0f}%", "match"), unsafe_allow_html=True)
    decision_tone = str(row.get("decision") or "neutral").lower()
    eligibility.markdown(_metric_card("Elegibilidad", _display_decision(row.get("decision")), decision_tone), unsafe_allow_html=True)
    hard_rejects = normalize_reason_list(reasons.get("hard_reject_reasons"))
    if hard_rejects:
        st.error("Motivo principal: " + hard_rejects[0])

    summary_tab, match_tab, application_tab, tracking_tab, cv_tab, description_tab, debug_tab = st.tabs(
        ["Resumen", "Match", "Postulación", "Seguimiento", "CV / Email", "Descripción", "Debug"]
    )
    requirements = reasons.get("job_requirements") or []
    matched = reasons.get("matched_requirements") or reasons.get("matched_skills") or []
    missing = reasons.get("missing_requirements") or reasons.get("missing_skills") or []
    with summary_tab:
        info = st.columns(3)
        info[0].markdown(_metric_card("Publicada", _display_time(row.get("published_at")), compact=True), unsafe_allow_html=True)
        info[1].markdown(_metric_card("Detectada", _display_time(row.get("first_seen_at")), compact=True), unsafe_allow_html=True)
        info[2].markdown(_metric_card("Estado", _display_status(status), "status", True), unsafe_allow_html=True)
        _render_items("Motivos positivos", reasons.get("positive_reasons") or [])
        st.markdown("#### Acciones")
        actions = st.columns(3)
        if is_internal_job_url(str(row["url"])): actions[0].caption("Sin URL pública · importada desde texto")
        else: actions[0].link_button("Abrir oferta original", row["url"], type="secondary")
        if row["decision"] in {"APPLY", "REVIEW"} and actions[1].button("⭐ Marcar para aplicar", key=f"short-{job_id}", type="primary"):
            database.set_application_status(job_id, "SHORTLISTED"); st.rerun()
        if actions[2].button("🗑️ Descartar", key=f"skip-{job_id}", type="secondary"):
            database.set_application_status(job_id, "SKIPPED"); st.rerun()
    with match_tab:
        cols = st.columns(3)
        with cols[0]: _render_items("Requisitos detectados", display_concepts(requirements))
        with cols[1]: _render_items("Coincidencias", display_concepts(matched))
        with cols[2]: _render_items("Gaps reales", display_concepts(missing))
        _render_items("Hard rejects", hard_rejects, "Ninguno")
        evidence = reasons.get("matched_requirement_evidence") or {}
        st.markdown("#### Evidencia factual del match")
        if evidence:
            for concept in matched:
                sources = evidence.get(concept) or []
                if sources:
                    with st.expander(display_concepts([concept])[0]):
                        for source in sources: st.write(f"• `{source}`")
        else: st.caption("Esta evaluación no tiene evidencia detallada registrada todavía.")
    cv_path, _ = _cv_paths(row)
    with application_tab: _render_application_channel(database, row, master_cv_path, cv_path)
    with tracking_tab: _render_tracking_card(database, row)
    with cv_tab: _render_cv_email_status(database, row, master_cv_path, cv_path)
    with description_tab:
        description = str(row.get("description") or "")
        if len(description) <= 1400: st.write(description or "Sin descripción")
        else:
            st.write(description[:1400].rsplit(" ", 1)[0] + "…")
            with st.expander("Ver descripción completa"): st.write(description)
    with debug_tab:
        with st.expander("Depuración técnica", expanded=False): st.json(reasons)


def _render_cv_email_status(database: JobDatabase, row: dict, master_cv_path: str, cv_path: Path) -> None:
    job_id, status = int(row["id"]), str(row["application_status"])
    pdf_path = cv_path.with_suffix(".pdf")
    status_cols = st.columns(3)
    status_cols[0].markdown(_badge("CV_GENERATED" if cv_path.exists() else "NOT_GENERATED", "status"), unsafe_allow_html=True)
    status_cols[1].markdown(_badge(row.get("cv_pdf_status") or "PDF_NOT_GENERATED", "status"), unsafe_allow_html=True)
    status_cols[2].markdown(_badge(row.get("email_draft_status") or "NOT_GENERATED", "channel"), unsafe_allow_html=True)
    if row["decision"] in {"APPLY", "REVIEW"}:
        label = "🔄 Regenerar CV" if cv_path.exists() else "📄 Generar CV"
        if st.button(label, key=f"cv-{job_id}", type="primary"):
            try:
                output, adapted = generate_job_cv(database.path, job_id, master_cv_path)
                st.success(f"CV {adapted.validation_status}: {output}"); st.rerun()
            except Exception as exc: st.error(str(exc))
    else: st.warning("La generación normal de CV está deshabilitada para REJECT.")
    if cv_path.exists():
        downloads = st.columns(2)
        downloads[0].download_button("Ver HTML", cv_path.read_text(encoding="utf-8"), cv_path.name, "text/html", key=f"view-{job_id}")
        if row.get("cv_pdf_status") == "PDF_VALID" and pdf_path.exists():
            downloads[1].download_button("Descargar PDF", pdf_path.read_bytes(), pdf_path.name, "application/pdf", key=f"pdf-{job_id}")
            st.caption(f"PDF válido · {row.get('cv_pdf_pages') or '—'} página(s)")
        elif row.get("cv_pdf_status") not in {"PDF_NOT_GENERATED", None}:
            st.warning(f"PDF inválido: {row.get('cv_pdf_status')}")
        if status == "CV_GENERATED" and st.button("👍 Aprobar para postular", key=f"approve-{job_id}"):
            database.set_application_status(job_id, "APPROVED_TO_APPLY"); st.rerun()


def _render_application_channel(database: JobDatabase, row: dict, master_cv_path: str, cv_path: Path) -> None:
    st.markdown("#### Canal de postulación")
    method, job_id = str(row.get("application_method") or "UNKNOWN"), int(row["id"])
    _badge_row((method, "channel"),)
    instructions = json.loads(row.get("application_instructions") or "[]")
    channel_cols = st.columns(2)
    channel_cols[0].write(f'**Destinatario:** {row.get("application_email") or "—"}')
    channel_cols[1].write(f'**Asunto requerido:** {row.get("email_subject") or "—"}')
    if instructions:
        _render_items("Instrucciones", instructions)
        language = "Inglés" if "CV en inglés" in instructions else "Español" if "CV en español" in instructions else "No especificado"
        st.caption(f"Idioma del CV: {language}")
    if method == "UNKNOWN": st.warning("No se pudo determinar un canal seguro."); return
    if method == "LINK_EMAIL":
        available = {"Postulación web": "LINK", "Postulación por email": "EMAIL"}
        current = row.get("selected_application_channel")
        choice = st.radio("Elegir canal", list(available), index=0 if current != "EMAIL" else 1, key=f"channel-{job_id}")
        if st.button("Confirmar canal", key=f"channel-save-{job_id}"):
            database.select_application_channel(job_id, available[choice]); st.rerun()
    elif not row.get("selected_application_channel"):
        database.select_application_channel(job_id, method)
        row = database.get_job_row(job_id) or row
    selected = row.get("selected_application_channel") or (method if method in {"LINK", "EMAIL"} else None)
    if method in {"LINK", "LINK_EMAIL"}:
        st.link_button("Abrir postulación", row.get("application_url") or row["url"])
        st.caption("Abrir el enlace no cambia el estado de la vacante.")
    if method not in {"EMAIL", "LINK_EMAIL"} or selected != "EMAIL": return
    st.write(f'Para: **{row.get("application_email") or "Requiere revisión"}**')
    pdf_path = cv_path.with_suffix(".pdf")
    pdf_valid = row.get("cv_pdf_status") == "PDF_VALID" and pdf_path.exists()
    st.write(f'CV PDF: {"✅ válido" if pdf_valid else "⏳ generar/validar primero"}')
    st.write(f'Email: **{row.get("email_draft_status") or "NOT_GENERATED"}**')
    if row.get("application_email") and pdf_valid and st.button("Preparar email", key=f"prepare-email-{job_id}", type="primary"):
        try: prepare_application_email(database.path, job_id, master_cv_path); st.rerun()
        except Exception as exc: st.error(str(exc))
    if row.get("email_draft_status") in {"GENERATED", "APPROVED", "GMAIL_DRAFT_CREATED"}:
        with st.form(f"email-edit-{job_id}"):
            recipient = st.text_input("Destinatario", row.get("application_email") or "")
            subject = st.text_input("Asunto", row.get("email_subject") or "")
            body = st.text_area("Cuerpo", row.get("email_body") or "", height=280)
            if st.form_submit_button("Guardar edición"):
                database.save_email_draft(job_id, recipient, subject, body); st.rerun()
    if row.get("email_draft_status") == "GENERATED" and st.button("Aprobar email", key=f"approve-email-{job_id}", type="primary"):
        database.approve_email_draft(job_id); st.rerun()
    if row.get("email_draft_status") == "APPROVED" and pdf_valid:
        st.write(f'**Destinatario:** {row.get("application_email")}')
        st.write(f'**Asunto:** {row.get("email_subject")}')
        st.write(f'**Adjunto:** {pdf_path}')
        confirmed = st.checkbox("Confirmo crear este borrador en mi Gmail", key=f"confirm-gmail-{job_id}")
        if st.button("Crear borrador en Gmail", disabled=not confirmed, key=f"gmail-draft-{job_id}", type="primary"):
            draft = EmailDraft(row["application_email"], row["email_subject"], row["email_body"], [str(pdf_path)])
            try: create_approved_gmail_draft(database, job_id, GmailEmailProvider(), draft); st.rerun()
            except Exception as exc: st.error(f"No se creó el borrador y el estado no cambió: {exc}")
    elif row.get("email_draft_status") == "APPROVED":
        st.warning("El email está aprobado, pero se requiere un PDF_VALID antes de crear el borrador Gmail.")
    elif row.get("email_draft_status") == "GMAIL_DRAFT_CREATED":
        st.success(f'Borrador Gmail existente: {row.get("gmail_draft_id")}')
    elif row.get("email_draft_status") == "GMAIL_DRAFT_STALE":
        st.warning("El contenido cambió después de crear el borrador. Creá uno nuevo.")


def _render_tracking_card(database: JobDatabase, row: dict) -> None:
    job_id = int(row["id"]); current = row.get("application_stage") or "NOT_APPLIED"
    st.markdown("#### SEGUIMIENTO")
    if current == "NOT_APPLIED":
        st.info("La vacante todavía no está registrada como postulada.")
        if st.button("Marcar como postulada", key=f"mark-applied-{job_id}", type="primary"):
            channel = row.get("selected_application_channel") or row.get("application_method")
            database.mark_applied(job_id, channel=channel if channel in {"EMAIL", "LINK"} else None)
            st.rerun()
        return
    tracked = tracking_row(row)
    cards = st.columns(4)
    cards[0].markdown(_metric_card("Etapa actual", STAGE_LABELS.get(current, current), _stage_tone(current), True), unsafe_allow_html=True)
    cards[1].markdown(_metric_card("Postulado", _display_time(row.get("applied_at")) if row.get("applied_at") else "Fecha no registrada", compact=True), unsafe_allow_html=True)
    cards[2].markdown(_metric_card("Días en etapa", tracked.get("days_in_stage") if tracked.get("days_in_stage") is not None else "—", compact=True), unsafe_allow_html=True)
    cards[3].markdown(_metric_card("Último movimiento", _display_time(row.get("stage_updated_at") or row.get("applied_at")), compact=True), unsafe_allow_html=True)
    if tracked.get("no_response_band"):
        days = tracked.get("days_since_applied") or 0
        st.warning(f'{tracked["no_response_band"]} sin respuesta' + (" · considerar follow-up" if days >= 7 else ""))
        if st.button("Cerrar sin respuesta", key=f"close-no-response-{job_id}"):
            database.set_application_stage(job_id, "CLOSED_NO_RESPONSE", note="Cierre manual sin respuesta")
            st.rerun()
    with st.form(f"stage-form-{job_id}"):
        options = list(STAGE_LABELS)[1:]
        selected = st.selectbox("Actualizar etapa", options, index=options.index(current),
                                format_func=lambda value: STAGE_LABELS[value])
        note = st.text_area("Nota opcional", placeholder="Sin secretos ni datos sensibles", height=80)
        if st.form_submit_button("Guardar etapa", disabled=selected == current):
            database.set_application_stage(job_id, selected, note=note); st.rerun()
    with st.form(f"next-action-{job_id}"):
        st.markdown("**Próxima acción**")
        action_at = st.text_input("Fecha/hora ISO (vacío para limpiar)", value=row.get("next_action_at") or "",
                                  placeholder="2026-09-05T11:00:00-03:00")
        action_note = st.text_input("Acción", value=row.get("next_action_note") or "")
        if st.form_submit_button("Guardar próxima acción"):
            database.set_next_action(job_id, action_at.strip() or None, action_note); st.rerun()
    history = database.application_history(job_id)
    st.markdown("**Historial**")
    if not history: st.caption("Sin eventos históricos; registro migrado sin fecha inventada.")
    for event in history:
        icon = "✅" if event["to_stage"] in {"APPLIED", "OFFER", "HIRED"} else "•"
        st.markdown(f'{icon} {_display_time(event["changed_at"])} · **{STAGE_LABELS.get(event["to_stage"], event["to_stage"])}**')
        if event.get("note"): st.caption(event["note"])


def _render_tracking_view(database: JobDatabase) -> None:
    st.subheader("Seguimiento")
    rows = [tracking_row(row) for row in database.tracking_jobs()]
    if not rows: st.info("Todavía no hay postulaciones registradas manualmente."); return
    filters = st.columns(6)
    selected_stage = filters[0].selectbox("Etapa", ["ALL", *list(STAGE_LABELS)[1:]],
        format_func=lambda value: "Todas" if value == "ALL" else STAGE_LABELS[value], key="tracking-stage")
    company = filters[1].text_input("Empresa", key="tracking-company").casefold()
    role = filters[2].text_input("Rol", key="tracking-role").casefold()
    source = filters[3].text_input("Fuente", key="tracking-source").casefold()
    channel = filters[4].selectbox("Canal", ["ALL", "EMAIL", "LINK", "LINK_EMAIL", "UNKNOWN"], key="tracking-channel")
    activity = filters[5].selectbox("Procesos", ["Todos", "Activos", "Cerrados"], key="tracking-activity")
    dates = st.columns(2)
    from_date = dates[0].date_input("Postuladas desde", value=None, key="tracking-from")
    to_date = dates[1].date_input("Postuladas hasta", value=None, key="tracking-to")
    filtered = []
    for row in rows:
        stage = row.get("application_stage") or "NOT_APPLIED"
        applied = parse_datetime(row.get("applied_at")) if row.get("applied_at") else None
        if selected_stage != "ALL" and stage != selected_stage: continue
        if company and company not in str(row.get("company") or "").casefold(): continue
        if role and role not in str(row.get("title") or "").casefold(): continue
        if source and source not in str(row.get("source") or "").casefold(): continue
        actual_channel = row.get("application_channel_used") or row.get("application_method") or "UNKNOWN"
        if channel != "ALL" and actual_channel != channel: continue
        if activity == "Activos" and stage not in ACTIVE_STAGES: continue
        if activity == "Cerrados" and stage not in CLOSED_STAGES: continue
        if from_date and (not applied or applied.date() < from_date): continue
        if to_date and (not applied or applied.date() > to_date): continue
        filtered.append(row)
    st.dataframe([{"Empresa": row["company"], "Puesto": row["title"],
        "Fecha postulación": _display_time(row.get("applied_at")) if row.get("applied_at") else "Fecha no registrada",
        "Etapa actual": STAGE_LABELS.get(row.get("application_stage"), row.get("application_stage")),
        "Último movimiento": _display_time(row.get("stage_updated_at") or row.get("applied_at")),
        "Días en etapa": row.get("days_in_stage"),
        "Próxima acción": " · ".join(filter(None, (_display_time(row.get("next_action_at")) if row.get("next_action_at") else "", row.get("next_action_note") or ""))),
        "Fuente": row.get("source"), "Canal": row.get("application_channel_used") or row.get("application_method"),
        "Score": float(row.get("score") or 0)} for row in filtered], hide_index=True, width="stretch")
    st.caption(f"{len(filtered)} proceso(s) · todo el tracking permanece en SQLite local.")


def _render_analytics_view(database: JobDatabase) -> None:
    st.subheader("Analytics")
    jobs = database.tracking_jobs()
    histories = {int(row["id"]): database.application_history(int(row["id"])) for row in jobs}
    data = analytics_snapshot(jobs, histories); kpis = data["kpis"]
    labels = (("Postulaciones hoy", "applications_today"), ("Esta semana", "applications_week"),
              ("Este mes", "applications_month"), ("Procesos activos", "active_processes"),
              ("Respuestas recibidas", "responses"), ("Entrevistas", "interviews"),
              ("Ofertas", "offers"), ("Contrataciones", "hires"))
    for batch in (labels[:4], labels[4:]):
        columns = st.columns(4)
        for column, (label, key) in zip(columns, batch):
            column.markdown(_metric_card(label, kpis[key], "status", True), unsafe_allow_html=True)
    rates = data["rates"]; rate_columns = st.columns(4)
    for column, (label, key) in zip(rate_columns, (("Response rate", "response_rate"),
            ("Interview rate", "interview_rate"), ("Offer rate", "offer_rate"), ("Hire rate", "hire_rate"))):
        column.metric(label, f'{rates[key]:.1f}%')
    st.markdown("#### Funnel")
    funnel_rows = [{"Etapa": key, "Vacantes": value} for key, value in data["funnel"].items()]
    st.dataframe(funnel_rows, hide_index=True, width="stretch"); st.bar_chart(funnel_rows, x="Etapa", y="Vacantes")
    st.markdown("#### Postulaciones por tiempo")
    if data["daily"]: st.line_chart(data["daily"], x="date", y="applications")
    else: st.caption("Sin fechas de postulación registradas.")
    st.dataframe(data["weekly"], hide_index=True, width="stretch")
    table_labels = (("Performance por rol", "by_role"), ("Performance por fuente", "by_source"),
                    ("Performance por canal", "by_channel"), ("Performance por match score", "by_score"))
    for label, key in table_labels:
        st.markdown(f"#### {label}"); st.dataframe(data[key], hide_index=True, width="stretch")
    st.markdown("#### Tiempos de respuesta")
    timing_rows = []
    for label, key in (("Primera respuesta", "time_to_first_response"), ("APPLIED → HR_INTERVIEW", "applied_to_hr_interview")):
        value = data["timings"][key]
        timing_rows.append({"Métrica": label, "Casos": value["count"], "Promedio días": value["average"],
                            "Mediana": value["median"], "Mínimo": value["minimum"], "Máximo": value["maximum"]})
    st.dataframe(timing_rows, hide_index=True, width="stretch")

st.set_page_config(page_title="Job Hunter Agent", layout="wide")
st.markdown("""
<style>
.block-container {padding-top:1.25rem;padding-bottom:3rem;max-width:1280px}
.jh-card {min-height:108px;padding:1rem 1.1rem;border-radius:.8rem;background:#151c28;border:1px solid #303a49;
box-shadow:0 5px 16px rgba(0,0,0,.18);display:flex;flex-direction:column;justify-content:center;margin-bottom:.55rem}
.jh-card-label {color:#b9c4d3;font-size:.78rem;font-weight:650;letter-spacing:.035em;text-transform:uppercase}
.jh-card-value {color:#f7f9fc;font-size:1.75rem;font-weight:750;line-height:1.2;margin-top:.3rem;overflow-wrap:anywhere}
.jh-card-note {color:#91a0b4;font-size:.72rem;margin-top:.3rem}.jh-card-compact {min-height:76px;padding:.72rem .9rem;box-shadow:none}
.jh-card-compact .jh-card-value {font-size:1.02rem}.jh-card-match {border-color:#426aa4;background:#172235}
.jh-card-apply {border-color:#2f8254;background:#14271f}.jh-card-review {border-color:#9a7628;background:#2a2517}
.jh-card-reject {border-color:#9a3e46;background:#2c181d}.jh-card-status {border-color:#465a80;background:#192131}
.jh-badge {display:inline-block;padding:.3rem .65rem;margin:.1rem .25rem .35rem 0;border-radius:999px;font-size:.78rem;
font-weight:700;letter-spacing:.02em;background:#222b38;color:#e8edf4;border:1px solid #3a4656}
.jh-apply {background:#173528;color:#8ce0ad;border-color:#2d694a}.jh-review {background:#352d16;color:#f0cf72;border-color:#6d5b24}
.jh-reject {background:#3a1d22;color:#f09ba3;border-color:#71353d}.jh-status {background:#1d2d49;color:#a9c8ff;border-color:#365783}
.jh-channel {background:#2b2140;color:#cdb6f4;border-color:#513f73}.jh-mode {background:#183438;color:#9bdbe0;border-color:#2d6268}
.jh-origin-auto {background:#17342d;color:#92e0c2;border-color:#2f725d}.jh-origin-manual {background:#2c2440;color:#d0bdf5;border-color:#59477d}
.jh-origin-unknown {background:#302f34;color:#c8c7cc;border-color:#56545d}
.jh-card-stage-response {border-color:#7056a8;background:#251d38}.jh-card-stage-interview {border-color:#a87b2b;background:#302719}
.jh-card-stage-offer {border-color:#39845b;background:#173124}.jh-card-stage-hired {border-color:#23945a;background:#10351f}
.jh-card-stage-rejected {border-color:#91434c;background:#341d22}
.jh-chip {display:inline-block;padding:.28rem .58rem;margin:.18rem .2rem .18rem 0;border-radius:.5rem;background:#202936;
border:1px solid #364252;color:#e3e9f1;font-size:.82rem}div[data-testid="stExpander"] {border-color:#354050;border-radius:.65rem}
@media (max-width:900px){.block-container{padding-left:1rem;padding-right:1rem}.jh-card{min-height:88px}.jh-card-value{font-size:1.35rem}}
h3,h4 {margin-top:.35rem!important;margin-bottom:.35rem!important}
</style>
""", unsafe_allow_html=True)
st.title("Job Hunter Agent")
st.caption("Descubrimiento, evaluación y preparación de CV con aprobación humana. No realiza postulaciones.")

with st.sidebar:
    st.header("Configuración local")
    profile_path = st.text_input("Perfil", "config/profile.yaml")
    st.caption("Agente local · aprobación humana activa")
    with st.expander("Configuración avanzada", expanded=False):
        database_path = st.text_input("SQLite", "data/jobs.db")
        master_cv_path = st.text_input("Master CV privado", "private/master_cv.yaml")
        discovery_limit = st.number_input("Límite por target", 1, 100, 25)
        max_age_days = st.number_input("Antigüedad máxima", 1, 365, 14)
        available_sources = ["remoteok", "arbeitnow", "greenhouse", "lever", "ashby", "workable", "generic"]
        source_names = st.multiselect("Fuentes", available_sources, default=["remoteok", "arbeitnow"])

database = JobDatabase(database_path)
profile = load_profile(profile_path)
schedule = profile.discovery_schedule
latest_run = database.latest_discovery_run()
next_run = next_schedule_time(schedule.get("times", [])) if schedule.get("enabled", True) else None
counts = database.dashboard_counts()
all_jobs = database.list_jobs()
origins = origin_summary(all_jobs)

top = st.columns(6)
for column, label, value, tone in zip(top,
    ("Descubiertas hoy", "Importadas hoy", "Recomendadas", "En revisión", "Postuladas", "CVs generados"),
    (counts["discovered_today"], counts["imported_today"], counts["recommended"], counts["review"], counts["applied"], counts["cvs"]),
    ("status", "stage-response", "apply", "review", "status", "status")):
    column.markdown(_metric_card(label, value, tone), unsafe_allow_html=True)
overview = st.columns(4)
overview[0].markdown(_metric_card("Última búsqueda", _display_time(latest_run.get("finished_at")) if latest_run else "Sin ejecuciones", compact=True), unsafe_allow_html=True)
overview[1].markdown(_metric_card("Próxima búsqueda", _display_time(next_run.isoformat()) if next_run else "Desactivada", compact=True), unsafe_allow_html=True)
overview[2].markdown(_metric_card("Estado discovery", latest_run.get("status") if latest_run else "Sin ejecuciones", "status", True), unsafe_allow_html=True)
overview[3].markdown(_metric_card("Total vacantes", len(all_jobs), compact=True, note=f"{database.new_since_latest_discovery()} desde último discovery"), unsafe_allow_html=True)
if latest_run:
    with st.expander("Último discovery automático", expanded=True):
        run_cards = st.columns(4)
        run_cards[0].markdown(_metric_card("Finalizó", _display_time(latest_run.get("finished_at")), compact=True), unsafe_allow_html=True)
        run_cards[1].markdown(_metric_card("Estado", latest_run.get("status"), "status", True), unsafe_allow_html=True)
        run_cards[2].markdown(_metric_card("Vacantes obtenidas", latest_run.get("preliminary", 0), compact=True), unsafe_allow_html=True)
        run_cards[3].markdown(_metric_card("Nuevas automáticas", latest_run.get("new_jobs", 0), compact=True), unsafe_allow_html=True)
        st.caption("Fuentes consultadas: " + ", ".join(json.loads(latest_run.get("sources") or "[]")))
        st.dataframe([{"Actualizadas": latest_run.get("updated_jobs", 0), "Duplicadas": latest_run.get("duplicates", 0),
                       "APPLY": latest_run.get("apply_count", 0), "REVIEW": latest_run.get("review_count", 0),
                       "REJECT": latest_run.get("reject_count", 0),
                       "Errores": "Sí" if latest_run.get("errors") not in {None, "", "{}", "[]"} else "No"}],
                     hide_index=True, width="stretch")

job_hunt_tab, tracking_main_tab, analytics_tab, knowledge_tab, system_tab = st.tabs(
    ["Job Hunt", "Seguimiento", "Analytics", "Knowledge Base", "System / Runs"]
)

with job_hunt_tab:
    with st.expander("Importar vacante", expanded=False):
        import_mode = st.radio("Origen", ["URL pública", "Texto pegado"], horizontal=True)
        if import_mode == "URL pública":
            import_url = st.text_input("Pegar URL", key="import_url")
            if st.button("Analizar URL", disabled=not import_url.strip()):
                with st.spinner("Detectando fuente · extrayendo · normalizando · deduplicando · evaluando..."):
                    st.session_state["import_result"] = import_job_from_url(import_url, profile, database)
        result = st.session_state.get("import_result")
        needs_manual = import_mode == "Texto pegado" or (result and result.status == ImportStatus.NEEDS_MANUAL_INPUT)
        if result and import_mode == "URL pública":
            icons = {ImportStatus.IMPORTED: "✅", ImportStatus.DUPLICATE: "♻️",
                     ImportStatus.NEEDS_MANUAL_INPUT: "⚠️", ImportStatus.UNSUPPORTED: "❌", ImportStatus.FAILED: "❌"}
            st.write(f"{icons[result.status]} **{result.status.value}** · {result.source_type} · {result.extraction_method}")
            if result.warnings: st.warning(" ".join(result.warnings))
            if result.status in {ImportStatus.IMPORTED, ImportStatus.DUPLICATE}:
                st.markdown(f"#### {result.title} · {result.company}")
                _badge_row((result.decision, str(result.decision).lower()),
                           (result.application_method, "channel"), (result.work_mode, "mode"))
                import_metrics = st.columns(3)
                import_metrics[0].markdown(_metric_card("Match técnico", f"{float(result.score or 0):.0f}%", "match"), unsafe_allow_html=True)
                import_metrics[1].markdown(_metric_card("Sector", result.sector or "Other", compact=True), unsafe_allow_html=True)
                import_metrics[2].markdown(_metric_card("Job ID", result.job_id or "—", compact=True), unsafe_allow_html=True)
                _render_items("Coincidencias", display_concepts(result.reasons.get("matched_requirements", [])))
                _render_items("Gaps reales", display_concepts(result.reasons.get("missing_requirements") or result.reasons.get("missing_skills", [])))
                hard = normalize_reason_list(result.reasons.get("hard_reject_reasons"))
                if hard: st.error("Elegibilidad: " + hard[0])
                with st.expander("Depuración técnica", expanded=False): st.json(result.reasons)
                imported_actions = st.columns(3)
                if imported_actions[0].button("Ver detalle", key="import-view"):
                    st.session_state["import_focus_job_id"] = result.job_id
                can_generate = result.decision in {"APPLY", "REVIEW"} and result.job_id is not None
                if imported_actions[1].button("Generar CV", key="import-cv", disabled=not can_generate):
                    try:
                        output, adapted = generate_job_cv(database.path, int(result.job_id), master_cv_path)
                        st.success(f"CV {adapted.validation_status}: {output}")
                    except Exception as exc:
                        st.error(str(exc))
                if imported_actions[2].button("Descartar", key="import-skip", disabled=result.job_id is None):
                    database.set_application_status(int(result.job_id), "SKIPPED")
                    st.rerun()
        if needs_manual:
            if result and result.source_type == "linkedin":
                st.info("LinkedIn no expuso suficiente información pública. Pegá el texto de la vacante y la analizamos igual.")
            with st.form("manual_job_import"):
                manual_url = st.text_input("URL opcional", value=(result.canonical_url if result else ""))
                columns = st.columns(2)
                manual_company = columns[0].text_input("Empresa")
                manual_title = columns[1].text_input("Puesto")
                manual_location = columns[0].text_input("Ubicación")
                manual_mode = columns[1].selectbox("Modalidad", ["unknown", "remote", "hybrid", "onsite"])
                manual_date = st.text_input("Fecha de publicación opcional")
                manual_description = st.text_area("Texto completo de la vacante", height=220)
                save_manual = st.form_submit_button("Guardar y analizar")
            if save_manual:
                company = manual_company.strip()
                title = manual_title.strip()
                description = manual_description.strip()
                missing_manual = [label for label, value in (("empresa", company), ("puesto", title),
                                  ("descripción", description)) if not value]
                if missing_manual:
                    st.error("Faltan campos obligatorios: " + ", ".join(missing_manual))
                else:
                    method = "PASTED_TEXT" if import_mode == "Texto pegado" else "MANUAL_FORM"
                    st.session_state["import_result"] = import_manual_job({"url": manual_url, "company": company,
                        "title": title, "location": manual_location, "work_mode": manual_mode,
                        "published_at": manual_date, "description": description}, profile, database, method=method)
                    st.rerun()

    action_row = st.columns([1, 3])
    if action_row[0].button("Buscar ofertas ahora", type="primary", width="stretch"):
        started = time.monotonic()
        try:
            with st.spinner("Consultando fuentes públicas..."):
                with DiscoveryLock(Path(database_path).parent / "discovery.lock"):
                    result = run_discovery_pipeline(
                        build_sources(profile, source_names), profile_path, database_path,
                        limit=int(discovery_limit), max_age_days=int(max_age_days),
                    )
            duration = time.monotonic() - started
            st.session_state["manual_discovery"] = {
                "Inicio": datetime.now().astimezone().isoformat(timespec="seconds"),
                "Fuentes": ", ".join(result.discovery.stats), "Nuevas": result.inserted,
                "Actualizadas": result.updated, "Duplicadas": result.discovery.duplicates,
                "Descartadas pre-score": sum(stat.rejected_pre_score for stat in result.discovery.stats.values()),
                "APPLY": sum(job.decision == "APPLY" for job in result.jobs),
                "REVIEW": sum(job.decision == "REVIEW" for job in result.jobs),
                "REJECT": sum(job.decision == "REJECT" for job in result.jobs),
                "Duración": f"{duration:.1f}s",
            }
            st.success("Discovery finalizado")
        except DiscoveryAlreadyRunning as exc: st.warning(str(exc))
        except Exception as exc: st.error(f"Discovery falló de forma controlada: {exc}")
    if st.session_state.get("manual_discovery"):
        discovery_summary = st.session_state["manual_discovery"]
        action_row[1].success(f'Discovery completado en {discovery_summary["Duración"]} · {discovery_summary["Fuentes"]}')
        discovery_metrics = st.columns(6)
        for column, key in zip(discovery_metrics, ("Nuevas", "Actualizadas", "Duplicadas", "APPLY", "REVIEW", "REJECT")):
            column.markdown(_metric_card(key, discovery_summary[key], key.lower() if key in {"APPLY", "REVIEW", "REJECT"} else "neutral", True), unsafe_allow_html=True)

    view_labels = {"Último discovery": "latest_discovery", "Nuevas hoy": "today", "Recomendadas": "recommended", "En revisión": "review",
                   "CVs generados": "cvs", "Postuladas": "applied", "Descartadas": "discarded"}
    selected_view = st.radio("Vista", list(view_labels), horizontal=True)
    view_key = view_labels[selected_view]
    rows = database.latest_discovery_jobs() if view_key == "latest_discovery" else database.list_jobs(view_key, "All")
    filter_columns = st.columns(6)
    selected_decision = filter_columns[0].selectbox(
        "Decisión", ["ALL", "APPLY", "REVIEW", "REJECT"],
        format_func=lambda value: "Todas" if value == "ALL" else _display_decision(value),
    )
    statuses = ["ALL", "NEW", "SHORTLISTED", "CV_GENERATED", "APPROVED_TO_APPLY", "APPLIED", "SKIPPED"]
    selected_status = filter_columns[1].selectbox(
        "Estado operativo", statuses, format_func=lambda value: "Todos" if value == "ALL" else _display_status(value),
    )
    selected_mode = filter_columns[2].selectbox(
        "Modalidad", ["ALL", "remote", "hybrid", "onsite", "unknown"],
        format_func=lambda value: "Todas" if value == "ALL" else WORK_MODE_LABELS[value],
    )
    sectors = ["All", *sorted({str(row.get("sector") or "Other") for row in rows})]
    selected_sector = filter_columns[3].selectbox("Sector", sectors, key="job_sector",
                                                   format_func=lambda value: "Todos" if value == "All" else value)
    channels = ["ALL", "EMAIL", "LINK", "LINK_EMAIL", "UNKNOWN"]
    selected_channel = filter_columns[4].selectbox(
        "Canal", channels, format_func=lambda value: "Todos" if value == "ALL" else _display_method(value),
    )
    selected_origin = filter_columns[5].selectbox(
        "Origen", ["ALL", AUTOMATIC_DISCOVERY, "MANUAL", UNKNOWN],
        format_func=lambda value: {"ALL": "Todos", AUTOMATIC_DISCOVERY: "Discovery automático",
                                   "MANUAL": "Importadas manualmente", UNKNOWN: "Origen no determinado"}[value],
    )
    rows = [row for row in rows
            if (selected_decision == "ALL" or row.get("decision") == selected_decision)
            and (selected_status == "ALL" or row.get("application_status") == selected_status)
            and (selected_mode == "ALL" or normalize_work_mode(row.get("work_mode"), row.get("description", "")) == selected_mode)
            and (selected_sector == "All" or (row.get("sector") or "Other") == selected_sector)
            and (selected_channel == "ALL" or (row.get("application_method") or "UNKNOWN") == selected_channel)]
    rows = filter_jobs_by_origin(rows, selected_origin)
    search = st.text_input("Buscar empresa o puesto", key="job_search").strip().casefold()
    rows = [row for row in rows if not search or search in str(row["company"]).casefold() or search in str(row["title"]).casefold()]
    if not rows:
        st.info("El último discovery se completó sin nuevas vacantes." if view_key == "latest_discovery"
                else "No hay ofertas en esta vista.")
    else:
        decision_icons = {"APPLY": "✅ Aplicar", "REVIEW": "🟡 Revisar", "REJECT": "🔴 Rechazar"}
        method_icons = {"LINK": "🔗 Link", "EMAIL": "✉️ Email", "LINK_EMAIL": "🔗+✉️ Link + Email", "UNKNOWN": "❔ No detectado"}
        table_rows = ([{"Puesto": row["title"], "Empresa": row["company"],
                        "Score": f'{float(row.get("score") or 0):.0f}%', "Decisión": decision_icons.get(row["decision"], _display_decision(row["decision"])),
                        "Modalidad": _display_work_mode(row["work_mode"], row["description"]),
                        "Fuente": row.get("source") or "—", "Fecha detección": _display_time(row["first_seen_at"])} for row in rows]
                      if view_key == "latest_discovery" else
                      [{"Puesto": row["title"], "Empresa": row["company"],
                        "Score": f'{float(row.get("score") or 0):.0f}%', "Decisión": decision_icons.get(row["decision"], _display_decision(row["decision"])),
                        "Estado": _display_status(row["application_status"]),
                        "Modalidad": _display_work_mode(row["work_mode"], row["description"]),
                        "Canal": method_icons.get(row.get("application_channel_used") or row.get("application_method"), "❔ No detectado"),
                        "Fecha": _display_time(row.get("published_at") or row["first_seen_at"])} for row in rows])
        st.dataframe(table_rows, hide_index=True, width="stretch", height=min(460, 42 + len(rows) * 36),
                     column_config={"Puesto": st.column_config.TextColumn(width="large"),
                                    "Empresa": st.column_config.TextColumn(width="medium")})
        choices = {f'#{row["id"]} · {_display_decision(row["decision"])} · {row["company"]} · {row["title"]}': row for row in rows}
        choice_labels = list(choices)
        focus_id = st.session_state.get("import_focus_job_id")
        focus_index = next((index for index, row in enumerate(rows) if row["id"] == focus_id), 0)
        selected = choices[st.selectbox("Detalle de vacante", choice_labels, index=focus_index)]
        _render_job_detail(database, selected, master_cv_path)

with tracking_main_tab:
    _render_tracking_view(database)

with analytics_tab:
    _render_analytics_view(database)

with knowledge_tab:
    st.subheader("Knowledge Base")
    st.caption("Validar y aprobar no modifica el master; aplicar siempre muestra el diff y requiere confirmación.")
    knowledge = KnowledgeUpdater(master_cv_path, "private/update_proposals.yaml", "private/knowledge_audit.jsonl", "private/backups")
    try: proposals = knowledge.store.list()
    except Exception as exc: proposals = []; st.error(str(exc))
    if not proposals: st.info("No hay propuestas.")
    else:
        st.dataframe([{"ID": p.id, "Tipo": p.type.value, "Título": p.title, "Estado": p.status.value,
                       "Evidencia": ", ".join(p.evidence), "Errores": "; ".join(p.validation_errors)} for p in proposals],
                     hide_index=True, width="stretch")
        proposal_id = st.selectbox("Propuesta", [p.id for p in proposals]); proposal = knowledge.store.get(proposal_id)
        with st.expander("Cambios propuestos · detalle técnico", expanded=False): st.json(proposal.proposed_changes)
        columns = st.columns(3)
        if columns[0].button("Validar"):
            try: knowledge.validate(proposal_id); st.rerun()
            except Exception as exc: st.error(str(exc))
        if columns[1].button("Aprobar"):
            try: knowledge.approve(proposal_id); st.rerun()
            except Exception as exc: st.error(str(exc))
        if columns[2].button("Rechazar"):
            try: knowledge.reject(proposal_id); st.rerun()
            except Exception as exc: st.error(str(exc))
        if proposal.status.value == "APPROVED":
            st.code(knowledge.preview(proposal_id), language="diff")
            confirmed = st.checkbox("Confirmo aplicar al master factual")
            if st.button("Aplicar al Master", disabled=not confirmed):
                try: knowledge.apply(proposal_id); st.rerun()
                except Exception as exc: st.error(f"Cambio revertido: {exc}")

with system_tab:
    st.subheader("System / Runs")
    system_metrics = st.columns(4)
    system_metrics[0].markdown(_metric_card("Jobs en SQLite", len(all_jobs), compact=True), unsafe_allow_html=True)
    system_metrics[1].markdown(_metric_card("Fuentes activas", len(source_names), compact=True), unsafe_allow_html=True)
    system_metrics[2].markdown(_metric_card("Discovery runs", len(database.list_discovery_runs()), compact=True), unsafe_allow_html=True)
    system_metrics[3].markdown(_metric_card("Importaciones", len(database.list_import_history()), compact=True), unsafe_allow_html=True)
    st.subheader("Gmail")
    gmail = GmailEmailProvider()
    account = database.latest_gmail_account()
    if not gmail.configured:
        st.info("⚪ Gmail todavía no está conectado. Falta private/gmail/client_secret.json")
    elif not gmail.authorized:
        st.warning("🟡 Credenciales disponibles, autorización pendiente")
    else:
        st.success(f"🟢 Gmail conectado{': ' + account if account else ''}")
    if st.button("Conectar Gmail", disabled=not gmail.configured):
        try:
            account = gmail.authorize()
            database.record_gmail_event("GMAIL_AUTHORIZED", "SUCCESS", account_email=account)
            st.success(f"Gmail conectado: {account}"); st.rerun()
        except Exception as exc:
            database.record_gmail_event("GMAIL_AUTHORIZED", "FAILED", error=str(exc))
            st.error(f"No se pudo autorizar Gmail: {exc}")
    st.caption("Scope: gmail.compose. La aplicación sólo crea borradores; el envío real está deshabilitado.")
    runs = database.list_discovery_runs()
    st.caption(f"Fuentes: {', '.join(source_names) or 'Ninguna'} · Horarios: {', '.join(schedule.get('times', [])) if schedule.get('enabled', True) else 'Desactivados'}")
    st.caption("Scheduler de Windows: scripts preparados; estado no consultado para evitar requerir privilegios.")
    if runs:
        st.dataframe([{"Run": run["id"], "Inicio": _display_time(run["started_at"]), "Fin": _display_time(run["finished_at"]),
                       "Estado": run["status"], "Fuentes": run["sources"], "Preliminares": run["preliminary"],
                       "Nuevas automáticas": run["new_jobs"], "Actualizadas": run["updated_jobs"], "Duplicadas": run["duplicates"],
                       "APPLY": run["apply_count"], "REVIEW": run["review_count"], "REJECT": run["reject_count"],
                       "Errores": "⚠️ Sí" if run["errors"] not in {None, "", "{}", "[]"} else "—"} for run in runs], hide_index=True, width="stretch")
        with st.expander("Errores y payloads de runs", expanded=False):
            for run in runs:
                if run["errors"] not in {None, "", "{}", "[]"}: st.code(f'Run #{run["id"]}: {run["errors"]}')
    else: st.info("Aún no hay ejecuciones registradas.")
    st.subheader("Importaciones manuales")
    import_cards = st.columns(2)
    import_cards[0].markdown(_metric_card("Importadas hoy", origins["manual_today"], "stage-response", True), unsafe_allow_html=True)
    import_cards[1].markdown(_metric_card("Importadas esta semana", origins["manual_week"], compact=True), unsafe_allow_html=True)
    imports = database.list_import_history()
    if imports:
        st.dataframe([{"Fecha": _display_time(row["imported_at"]), "Empresa": row["company"],
                       "Puesto": row["title"], "Fuente": row["source_type"], "Resultado": row["result"],
                       "Job ID": row["job_id"], "Duplicate": row["duplicate_job_id"],
                       "Avisos": "⚠️" if row["warnings"] not in {None, "", "[]"} else "—"} for row in imports], hide_index=True, width="stretch")
        with st.expander("Avisos técnicos de importación", expanded=False):
            for row in imports:
                if row["warnings"] not in {None, "", "[]"}: st.code(f'{_display_time(row["imported_at"])} · {row["company"]}: {row["warnings"]}')
    else:
        st.info("Todavía no hay importaciones manuales.")
    st.subheader("Source Intelligence")
    metric_sectors = ["All", "Fintech", "Banking", "Retail", "E-commerce", "Consulting", "Technology", "SaaS", "Logistics", "Telecom", "Other"]
    metric_sector = st.selectbox("Filtrar métricas por sector", metric_sectors)
    intelligence = database.source_intelligence(metric_sector)
    if intelligence:
        st.dataframe([{"Fuente": row["source"], "Target": row["target"], "Sector": row["sector"],
                       "Fetched": row["fetched"], "Relevant": row["relevant"], "APPLY": row["apply_count"],
                       "REVIEW": row["review_count"], "REJECT": row["reject_count"],
                       "Duplicates": row["duplicates"], "Errors": row["errors"],
                       "Quality Score": row["quality_score"], "Health": row["health"],
                       "Última ejecución": _display_time(row["last_run"])} for row in intelligence],
                     hide_index=True, width="stretch")
    else:
        st.info("Todavía no hay métricas por fuente/target.")
