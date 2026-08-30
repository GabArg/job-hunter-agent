from __future__ import annotations

from .models import FactualText


class SummaryComposer:
    def compose(self, facts: list[FactualText], keywords: list[str] | None = None) -> tuple[str, list[str]]:
        raise NotImplementedError


class RuleBasedSummaryComposer(SummaryComposer):
    def compose(self, facts: list[FactualText], keywords: list[str] | None = None) -> tuple[str, list[str]]:
        by_id = {fact.id: fact for fact in facts}
        keywords = keywords or []
        sentences: list[str] = []
        used: list[str] = []

        if any(value in keywords for value in ("n8n", "ai-agents", "chatbots")):
            if "summary_01" in by_id and "summary_02" in by_id:
                sentences.append("Profesional con amplia trayectoria comercial y operativa, actualmente orientado a Data Analytics y Business Analytics.")
                used.extend(["summary_01", "summary_02"])
            if "summary_09" in by_id:
                sentences.append("Cuenta con experiencia práctica utilizando IA generativa y agentes para análisis, documentación, prototipado y automatización.")
                used.append("summary_09")
            if "summary_06" in by_id:
                sentences.append("Automatiza registros, controles y procesos mediante herramientas de datos y hojas de cálculo.")
                used.append("summary_06")
            return " ".join(sentences[:3]), used

        if any(value in keywords for value in ("etl", "data-ingestion", "postgresql")):
            if "summary_01" in by_id and "summary_02" in by_id:
                sentences.append("Profesional con amplia trayectoria comercial y operativa, actualmente orientado a Data Analytics y Business Analytics.")
                used.extend(["summary_01", "summary_02"])
            if "summary_07" in by_id:
                sentences.append("Combina conocimiento del negocio con formación y experiencia práctica en SQL, Python y herramientas cloud.")
                used.append("summary_07")
            if "summary_06" in by_id:
                sentences.append("Aplica automatización de registros, controles y procesos para convertir necesidades operativas en soluciones de datos.")
                used.append("summary_06")
            return " ".join(sentences[:3]), used

        if "summary_04" in by_id:
            if "summary_01" in by_id:
                sentences.append("Profesional con más de 20 años de trayectoria en gestión comercial y operativa.")
                used.append("summary_01")
            sentences.append(
                "Cuenta con experiencia analizando ventas, costos, márgenes, rentabilidad, clientes, productos e inventarios para comprender el desempeño del negocio."
            )
            used.append("summary_04")
            if "summary_02" in by_id and "summary_07" in by_id:
                sentences.append(
                    "Actualmente orienta esa experiencia hacia Data Analytics y Business Analytics, apoyándose en SQL, Python, Power BI y Excel."
                )
                used.extend(["summary_02", "summary_07"])
            if "summary_03" in by_id and "summary_05" in by_id:
                sentences.append(
                    "Aplica KPIs, reportes, tableros y controles para respaldar decisiones comerciales y operativas."
                )
                used.extend(["summary_03", "summary_05"])
            return " ".join(sentences[:3]), used

        if "summary_01" in by_id and "summary_02" in by_id:
            sentences.append(
                "Profesional con más de 20 años de trayectoria comercial y operativa, actualmente orientado a Data Analytics y Business Analytics."
            )
            used.extend(["summary_01", "summary_02"])
        if "summary_07" in by_id:
            sentences.append(
                "Combina conocimiento del negocio con experiencia práctica en SQL, Python, Power BI y Excel para el trabajo analítico."
            )
            used.append("summary_07")
        if "summary_03" in by_id and "summary_05" in by_id:
            sentences.append(
                "Diseña y monitorea KPIs, reportes, tableros y controles para respaldar decisiones comerciales y operativas."
            )
            used.extend(["summary_03", "summary_05"])
        if "summary_08" in by_id and len(sentences) < 3:
            sentences.append("Conecta problemas operativos y necesidades de negocio con soluciones analíticas accionables.")
            used.append("summary_08")

        if not sentences:
            selected = facts[:4]
            return " ".join(fact.text for fact in selected), [fact.id for fact in selected]
        return " ".join(sentences[:3]), used
