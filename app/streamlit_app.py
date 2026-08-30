from __future__ import annotations

import json
import time
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
from job_hunter.importer import ImportStatus, import_job_from_url, import_manual_job


def _display_time(value) -> str:
    if not value: return "—"
    parsed = parse_datetime(value)
    return parsed.astimezone().strftime("%d/%m/%Y %H:%M") if parsed else str(value)


def _display_work_mode(value, description: str = "") -> str:
    return normalize_work_mode(value, description).title()


def _render_job_detail(database: JobDatabase, row: dict, master_cv_path: str) -> None:
    reasons = json.loads(str(row["reasons"]))
    st.subheader(f'{row["decision"]} · {row["title"]}')
    st.write(f'**{row["company"]}** · {row["location"]} · {_display_work_mode(row["work_mode"], row["description"])} · {row["source"]}')
    st.write(f'Publicada: {_display_time(row["published_at"])} · Detectada: {_display_time(row["first_seen_at"])} · Score: {row["score"]:.2f}')
    st.write(f'Estado operativo: **{row["application_status"]}**')
    st.markdown(f'[Abrir oferta original]({row["url"]})')
    cols = st.columns(4)
    requirements = reasons.get("job_requirements") or []
    matched = reasons.get("matched_requirements") or reasons.get("matched_skills") or []
    missing = reasons.get("missing_skills") or []
    hard_rejects = normalize_reason_list(reasons.get("hard_reject_reasons"))
    cols[0].write("**Requisitos detectados**"); cols[0].write(display_concepts(requirements) or ["—"])
    cols[1].write("**Match del candidato**"); cols[1].write(display_concepts(matched) or ["—"])
    cols[2].write("**Gaps reales**"); cols[2].write(display_concepts(missing) or ["—"])
    cols[3].write("**Hard rejects**"); cols[3].write(hard_rejects or ["Ninguno"])
    st.write("**Motivos positivos:**", reasons.get("positive_reasons") or ["—"])
    with st.expander("Descripción completa"): st.write(row["description"])
    job_id, status = int(row["id"]), str(row["application_status"])
    actions = st.columns(3)
    if row["decision"] in {"APPLY", "REVIEW"}:
        label = "Regenerar CV" if status in {"CV_GENERATED", "APPROVED_TO_APPLY", "APPLIED"} else "Generar CV"
        if actions[0].button(label, key=f"cv-{job_id}"):
            try:
                output, adapted = generate_job_cv(database.path, job_id, master_cv_path)
                st.success(f"CV {adapted.validation_status}: {output}"); st.rerun()
            except Exception as exc: st.error(str(exc))
        if actions[1].button("Marcar para aplicar", key=f"short-{job_id}"):
            database.set_application_status(job_id, "SHORTLISTED"); st.rerun()
        if actions[2].button("Descartar", key=f"skip-{job_id}"):
            database.set_application_status(job_id, "SKIPPED"); st.rerun()
    else: st.warning("REJECT: la generación normal de CV está deshabilitada.")
    cv_path = Path("outputs/cvs") / str(job_id) / "cv.html"
    pdf_path = Path("outputs/cvs") / str(job_id) / "cv.pdf"
    if cv_path.exists():
        st.download_button("Ver HTML", cv_path.read_text(encoding="utf-8"), "cv.html", "text/html", key=f"view-{job_id}")
        pdf_status = row.get("cv_pdf_status") or "PDF_NOT_GENERATED"
        pages = row.get("cv_pdf_pages")
        if pdf_status == "PDF_VALID" and pdf_path.exists():
            st.success(f"PDF: VALID · {pages} página{'s' if pages != 1 else ''}")
            st.download_button("Descargar PDF", pdf_path.read_bytes(), "cv.pdf", "application/pdf", key=f"pdf-{job_id}")
        elif pdf_status not in {"PDF_NOT_GENERATED", None}:
            st.warning(f"PDF inválido: {pdf_status}")
        if status == "CV_GENERATED" and st.button("Aprobar para postular", key=f"approve-{job_id}"):
            database.set_application_status(job_id, "APPROVED_TO_APPLY"); st.rerun()
    if status == "APPROVED_TO_APPLY" and st.button("Marcar como postulada", key=f"applied-{job_id}"):
        if row.get("selected_application_channel") == "LINK" or row.get("application_method") == "LINK":
            database.mark_link_applied(job_id); st.rerun()
        else: st.warning("Seleccioná el canal usado antes de marcar la postulación.")
    _render_application_channel(database, row, master_cv_path, cv_path)


def _render_application_channel(database: JobDatabase, row: dict, master_cv_path: str, cv_path: Path) -> None:
    st.divider(); st.subheader("Canal de postulación")
    method, job_id = str(row.get("application_method") or "UNKNOWN"), int(row["id"])
    st.write(f"Método detectado: **{method.replace('_', ' + ')}**")
    instructions = json.loads(row.get("application_instructions") or "[]")
    if instructions: st.write("**Instrucciones:**", instructions)
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
        if selected == "LINK" and st.button("Marcar como postulada por link", key=f"link-applied-{job_id}"):
            database.mark_link_applied(job_id); st.rerun()
    if method not in {"EMAIL", "LINK_EMAIL"} or selected != "EMAIL": return
    st.write(f'Para: **{row.get("application_email") or "Requiere revisión"}**')
    pdf_path = cv_path.with_suffix(".pdf")
    pdf_valid = row.get("cv_pdf_status") == "PDF_VALID" and pdf_path.exists()
    st.write(f'CV PDF: {"✅ válido" if pdf_valid else "⏳ generar/validar primero"}')
    st.write(f'Email: **{row.get("email_draft_status") or "NOT_GENERATED"}**')
    if row.get("application_email") and pdf_valid and st.button("Preparar email", key=f"prepare-email-{job_id}"):
        try: prepare_application_email(database.path, job_id, master_cv_path); st.rerun()
        except Exception as exc: st.error(str(exc))
    if row.get("email_draft_status") in {"GENERATED", "APPROVED", "GMAIL_DRAFT_CREATED"}:
        with st.form(f"email-edit-{job_id}"):
            recipient = st.text_input("Destinatario", row.get("application_email") or "")
            subject = st.text_input("Asunto", row.get("email_subject") or "")
            body = st.text_area("Cuerpo", row.get("email_body") or "", height=280)
            if st.form_submit_button("Guardar edición"):
                database.save_email_draft(job_id, recipient, subject, body); st.rerun()
    if row.get("email_draft_status") == "GENERATED" and st.button("Aprobar email", key=f"approve-email-{job_id}"):
        database.approve_email_draft(job_id); st.rerun()
    if row.get("email_draft_status") == "APPROVED" and pdf_valid:
        st.write(f'**Destinatario:** {row.get("application_email")}')
        st.write(f'**Asunto:** {row.get("email_subject")}')
        st.write(f'**Adjunto:** {pdf_path}')
        confirmed = st.checkbox("Confirmo crear este borrador en mi Gmail", key=f"confirm-gmail-{job_id}")
        if st.button("Crear borrador en Gmail", disabled=not confirmed, key=f"gmail-draft-{job_id}"):
            draft = EmailDraft(row["application_email"], row["email_subject"], row["email_body"], [str(pdf_path)])
            try: create_approved_gmail_draft(database, job_id, GmailEmailProvider(), draft); st.rerun()
            except Exception as exc: st.error(f"No se creó el borrador y el estado no cambió: {exc}")
    elif row.get("email_draft_status") == "APPROVED":
        st.warning("El email está aprobado, pero se requiere un PDF_VALID antes de crear el borrador Gmail.")
    elif row.get("email_draft_status") == "GMAIL_DRAFT_CREATED":
        st.success(f'Borrador Gmail existente: {row.get("gmail_draft_id")}')
    elif row.get("email_draft_status") == "GMAIL_DRAFT_STALE":
        st.warning("El contenido cambió después de crear el borrador. Creá uno nuevo.")

st.set_page_config(page_title="Job Hunter Agent", layout="wide")
st.title("Job Hunter Agent")
st.caption("Descubrimiento, evaluación y preparación de CV con aprobación humana. No realiza postulaciones.")

with st.sidebar:
    st.header("Configuración local")
    profile_path = st.text_input("Perfil", "config/profile.yaml")
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

top = st.columns(3)
top[0].metric("Última búsqueda", _display_time(latest_run.get("finished_at")) if latest_run else "Sin ejecuciones")
top[1].metric("Próxima búsqueda", _display_time(next_run.isoformat()) if next_run else "Desactivada")
top[2].metric("Nuevas desde último discovery", database.new_since_latest_discovery())

job_hunt_tab, knowledge_tab, system_tab = st.tabs(["Job Hunt", "Knowledge Base", "System / Runs"])

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
                st.json({"job_id": result.job_id, "decision": result.decision, "score": result.score,
                         "company": result.company, "title": result.title, "sector": result.sector,
                         "work_mode": result.work_mode, "application_method": result.application_method,
                         "positive_reasons": result.reasons.get("positive_reasons", []),
                         "gaps": result.reasons.get("missing_skills", []),
                         "hard_rejects": result.reasons.get("hard_reject_reasons", [])})
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
                save_manual = st.form_submit_button("Guardar y analizar", disabled=not manual_description.strip())
            if save_manual:
                method = "PASTED_TEXT" if import_mode == "Texto pegado" else "MANUAL_FORM"
                st.session_state["import_result"] = import_manual_job({"url": manual_url, "company": manual_company,
                    "title": manual_title, "location": manual_location, "work_mode": manual_mode,
                    "published_at": manual_date, "description": manual_description}, profile, database, method=method)
                st.rerun()

    action_row = st.columns([1, 3])
    if action_row[0].button("Buscar ofertas ahora", type="primary", use_container_width=True):
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
        action_row[1].json(st.session_state["manual_discovery"])

    counts = database.dashboard_counts()
    labels = [("Nuevas hoy", "new_today"), ("Recomendadas", "recommended"), ("En revisión", "review"),
              ("CVs generados", "cvs"), ("Postuladas", "applied"), ("Descartadas", "discarded")]
    for column, (label, key) in zip(st.columns(6), labels): column.metric(label, counts[key])

    view_labels = {"Nuevas hoy": "today", "Recomendadas": "recommended", "En revisión": "review",
                   "CVs generados": "cvs", "Postuladas": "applied", "Descartadas": "discarded"}
    selected_view = st.radio("Vista", list(view_labels), horizontal=True)
    sectors = ["All", "Fintech", "Banking", "Retail", "E-commerce", "Consulting", "Technology", "SaaS", "Logistics", "Telecom", "Other"]
    selected_sector = st.selectbox("Sector", sectors, key="job_sector")
    rows = database.list_jobs(view_labels[selected_view], selected_sector)
    search = st.text_input("Buscar empresa o puesto", key="job_search").strip().casefold()
    rows = [row for row in rows if not search or search in str(row["company"]).casefold() or search in str(row["title"]).casefold()]
    if not rows:
        st.info("No hay ofertas en esta vista.")
    else:
        st.dataframe([{"ID": row["id"], "Decisión": row["decision"], "Score": row["score"],
                       "Estado": row["application_status"], "Empresa": row["company"], "Puesto": row["title"],
                       "Sector": row.get("sector") or "Other", "Nueva <72h": "🆕" if row.get("priority_fresh") else "",
                       "Modalidad": _display_work_mode(row["work_mode"], row["description"]), "Método": row.get("application_channel_used") or row.get("application_method"),
                       "Destinatario": row.get("application_email") or "", "Aplicada": _display_time(row.get("applied_at")),
                       "Detectada": _display_time(row["first_seen_at"]), "Oferta": row["url"]}
                      for row in rows], hide_index=True, use_container_width=True,
                     column_config={"Oferta": st.column_config.LinkColumn("Oferta")})
        choices = {f'#{row["id"]} · {row["decision"]} · {row["company"]} · {row["title"]}': row for row in rows}
        choice_labels = list(choices)
        focus_id = st.session_state.get("import_focus_job_id")
        focus_index = next((index for index, row in enumerate(rows) if row["id"] == focus_id), 0)
        selected = choices[st.selectbox("Detalle de vacante", choice_labels, index=focus_index)]
        _render_job_detail(database, selected, master_cv_path)

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
                     hide_index=True, use_container_width=True)
        proposal_id = st.selectbox("Propuesta", [p.id for p in proposals]); proposal = knowledge.store.get(proposal_id)
        st.json(proposal.proposed_changes)
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
    st.write(f"Ofertas en SQLite: {len(database.list_jobs())}")
    st.write(f"Fuentes activas: {', '.join(source_names) or 'Ninguna'}")
    st.write(f"Horarios locales: {', '.join(schedule.get('times', [])) if schedule.get('enabled', True) else 'Desactivados'}")
    st.write("Scheduler de Windows: scripts preparados; estado no consultado para evitar requerir privilegios.")
    if runs:
        st.dataframe([{"ID": run["id"], "Inicio": _display_time(run["started_at"]), "Fin": _display_time(run["finished_at"]),
                       "Estado": run["status"], "Fuentes": run["sources"], "Preliminares": run["preliminary"],
                       "Nuevas": run["new_jobs"], "Actualizadas": run["updated_jobs"], "Duplicadas": run["duplicates"],
                       "APPLY": run["apply_count"], "REVIEW": run["review_count"], "REJECT": run["reject_count"],
                       "Errores": run["errors"]} for run in runs], hide_index=True, use_container_width=True)
    else: st.info("Aún no hay ejecuciones registradas.")
    st.subheader("Importaciones manuales")
    imports = database.list_import_history()
    if imports:
        st.dataframe([{"Fecha": _display_time(row["imported_at"]), "Empresa": row["company"],
                       "Puesto": row["title"], "Fuente": row["source_type"], "Resultado": row["result"],
                       "Job ID": row["job_id"], "Duplicate": row["duplicate_job_id"],
                       "Warnings": row["warnings"]} for row in imports], hide_index=True, use_container_width=True)
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
                     hide_index=True, use_container_width=True)
    else:
        st.info("Todavía no hay métricas por fuente/target.")
