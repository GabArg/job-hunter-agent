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
from job_hunter.operations import generate_job_cv, next_schedule_time
from job_hunter.pipeline import run_discovery_pipeline
from job_hunter.discovery.matching import parse_datetime
from job_hunter.scorer import normalize_reason_list
from job_hunter.semantics import display_concepts


def _display_time(value) -> str:
    if not value: return "—"
    parsed = parse_datetime(value)
    return parsed.astimezone().strftime("%d/%m/%Y %H:%M") if parsed else str(value)


def _render_job_detail(database: JobDatabase, row: dict, master_cv_path: str) -> None:
    reasons = json.loads(str(row["reasons"]))
    st.subheader(f'{row["decision"]} · {row["title"]}')
    st.write(f'**{row["company"]}** · {row["location"]} · {row["work_mode"]} · {row["source"]}')
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
    if cv_path.exists():
        st.download_button("Ver / descargar CV", cv_path.read_text(encoding="utf-8"), "cv.html", "text/html", key=f"view-{job_id}")
        if status == "CV_GENERATED" and st.button("Aprobar para postular", key=f"approve-{job_id}"):
            database.set_application_status(job_id, "APPROVED_TO_APPLY"); st.rerun()
    if status == "APPROVED_TO_APPLY" and st.button("Marcar como postulada", key=f"applied-{job_id}"):
        database.set_application_status(job_id, "APPLIED"); st.rerun()

st.set_page_config(page_title="Job Hunter Agent", layout="wide")
st.title("Job Hunter Agent")
st.caption("Descubrimiento, evaluación y preparación de CV con aprobación humana. No realiza postulaciones.")

with st.sidebar:
    st.header("Configuración local")
    profile_path = st.text_input("Perfil", "config/profile.yaml")
    database_path = st.text_input("SQLite", "data/jobs.db")
    master_cv_path = st.text_input("Master CV privado", "private/master_cv.yaml")
    discovery_limit = st.number_input("Límite por fuente", 1, 100, 10)
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
    rows = database.list_jobs(view_labels[selected_view])
    search = st.text_input("Buscar empresa o puesto", key="job_search").strip().casefold()
    rows = [row for row in rows if not search or search in str(row["company"]).casefold() or search in str(row["title"]).casefold()]
    if not rows:
        st.info("No hay ofertas en esta vista.")
    else:
        st.dataframe([{"ID": row["id"], "Decisión": row["decision"], "Score": row["score"],
                       "Estado": row["application_status"], "Empresa": row["company"], "Puesto": row["title"],
                       "Modalidad": row["work_mode"], "Detectada": _display_time(row["first_seen_at"]), "Oferta": row["url"]}
                      for row in rows], hide_index=True, use_container_width=True,
                     column_config={"Oferta": st.column_config.LinkColumn("Oferta")})
        choices = {f'#{row["id"]} · {row["decision"]} · {row["company"]} · {row["title"]}': row for row in rows}
        selected = choices[st.selectbox("Detalle de vacante", list(choices))]
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
