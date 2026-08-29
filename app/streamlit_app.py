from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import streamlit as st

from job_hunter.database import JobDatabase
from job_hunter.discovery.sources import ArbeitnowSource, RemoteOKSource
from job_hunter.pipeline import run_discovery_pipeline, run_pipeline

st.set_page_config(page_title="Job Hunter Agent", layout="wide")
st.title("Job Hunter Agent")
st.caption("Clasificación local y explicable. Esta V1 no realiza postulaciones.")

with st.sidebar:
    st.header("Pipeline")
    csv_path = st.text_input("CSV", "data/sample_jobs.csv")
    profile_path = st.text_input("Perfil", "config/profile.yaml")
    database_path = st.text_input("SQLite", "data/jobs.db")
    if st.button("Importar y evaluar", type="primary"):
        try:
            result = run_pipeline(csv_path, profile_path, database_path)
            st.success(f"{len(result.jobs)} procesadas: {result.inserted} nuevas, {result.updated} actualizadas")
        except Exception as exc:
            st.error(str(exc))
    st.divider()
    st.header("Discovery")
    discovery_query = st.text_input("Consulta opcional", placeholder="Usar búsquedas del perfil")
    discovery_limit = st.number_input("Límite por fuente", min_value=1, max_value=100, value=10)
    source_names = st.multiselect("Fuentes", ["remoteok", "arbeitnow"], default=["remoteok", "arbeitnow"])
    if st.button("Descubrir ofertas"):
        try:
            factories = {"remoteok": RemoteOKSource, "arbeitnow": ArbeitnowSource}
            discovery_run = run_discovery_pipeline(
                [factories[name]() for name in source_names], profile_path, database_path,
                queries=[discovery_query] if discovery_query else None, limit=int(discovery_limit),
            )
            st.session_state["last_discovery"] = {
                "at": datetime.now().astimezone().isoformat(timespec="seconds"),
                "found": sum(stat.found for stat in discovery_run.discovery.stats.values()),
                "new": discovery_run.inserted,
                "duplicates": discovery_run.discovery.duplicates + discovery_run.updated,
                "errors": discovery_run.discovery.errors,
                "decisions": {
                    decision: sum(job.decision == decision for job in discovery_run.jobs)
                    for decision in ("APPLY", "REVIEW", "REJECT")
                },
                "stats": discovery_run.discovery.stats,
            }
            st.success(f"Discovery finalizado: {len(discovery_run.jobs)} ofertas procesadas")
        except Exception as exc:
            st.error(f"No se pudo completar discovery: {exc}")

last_discovery = st.session_state.get("last_discovery")
if last_discovery:
    st.subheader("Última ejecución de Discovery")
    st.caption(last_discovery["at"])
    discovery_metrics = st.columns(3)
    discovery_metrics[0].metric("Encontradas", last_discovery["found"])
    discovery_metrics[1].metric("Nuevas", last_discovery["new"])
    discovery_metrics[2].metric("Duplicadas", last_discovery["duplicates"])
    decision_metrics = st.columns(3)
    for column, (decision, count) in zip(decision_metrics, last_discovery["decisions"].items()):
        column.metric(decision, count)
    source_rows = [
        {
            "Fuente": name,
            "Encontradas": stat.found,
            "Aceptadas": stat.accepted,
            "Duplicadas": stat.duplicates,
            "Filtradas": stat.filtered,
            "Error": stat.error or "",
        }
        for name, stat in last_discovery["stats"].items()
    ]
    st.dataframe(source_rows, hide_index=True, use_container_width=True)

if not Path(database_path).exists():
    st.info("Ejecutá el pipeline para crear la base de datos.")
    st.stop()

rows = JobDatabase(database_path).list_jobs()
if not rows:
    st.info("Todavía no hay ofertas.")
    st.stop()

counts = {decision: sum(row["decision"] == decision for row in rows) for decision in ("APPLY", "REVIEW", "REJECT")}
columns = st.columns(3)
for column, decision in zip(columns, counts):
    column.metric(decision, counts[decision])

selected = st.multiselect("Filtrar por decisión", list(counts), default=list(counts))
search = st.text_input("Buscar por empresa o puesto").strip().lower()
filtered = [
    row for row in rows
    if row["decision"] in selected
    and (not search or search in str(row["company"]).lower() or search in str(row["title"]).lower())
]

display_rows = []
for row in filtered:
    reasons = json.loads(str(row["reasons"]))
    explanation = reasons["hard_reject_reasons"] or reasons["positive_reasons"]
    display_rows.append({
        "Score": row["score"],
        "Empresa": row["company"],
        "Puesto": row["title"],
        "Modalidad": row["work_mode"],
        "Decisión": row["decision"],
        "Motivos": " · ".join(explanation),
        "Oferta": row["url"],
    })

st.dataframe(
    display_rows,
    use_container_width=True,
    hide_index=True,
    column_config={"Oferta": st.column_config.LinkColumn("Oferta")},
)
