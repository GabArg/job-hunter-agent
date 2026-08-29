from __future__ import annotations

import json
from pathlib import Path

import streamlit as st

from job_hunter.database import JobDatabase
from job_hunter.pipeline import run_pipeline

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
