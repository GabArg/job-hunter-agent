from __future__ import annotations

from .models import FactualText


class SummaryComposer:
    def compose(self, facts: list[FactualText]) -> tuple[str, list[str]]:
        raise NotImplementedError


class RuleBasedSummaryComposer(SummaryComposer):
    def compose(self, facts: list[FactualText]) -> tuple[str, list[str]]:
        by_id = {fact.id: fact for fact in facts}
        sentences: list[str] = []
        used: list[str] = []

        if "summary_01" in by_id and "summary_02" in by_id:
            sentences.append(
                "Profesional con más de 20 años de trayectoria comercial y operativa, actualmente orientado a Data Analytics y Business Analytics."
            )
            used.extend(["summary_01", "summary_02"])
        if "summary_07" in by_id:
            sentences.append(
                "Combina conocimiento del negocio con experiencia práctica en SQL, Python, Power BI, Excel, estadística y herramientas cloud."
            )
            used.append("summary_07")
        if "summary_03" in by_id and "summary_05" in by_id:
            sentences.append(
                "Diseña y monitorea KPIs, reportes, tableros y controles para respaldar decisiones comerciales y operativas."
            )
            used.extend(["summary_03", "summary_05"])
        if "summary_08" in by_id:
            sentences.append(
                "Su enfoque conecta problemas operativos y necesidades de negocio con soluciones analíticas accionables."
            )
            used.append("summary_08")

        if not sentences:
            selected = facts[:4]
            return " ".join(fact.text for fact in selected), [fact.id for fact in selected]
        return " ".join(sentences[:4]), used
