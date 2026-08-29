from __future__ import annotations

from .models import FactualText

# Approved meaning-preserving editorial rewrites. The validator uses this same
# deterministic function, so arbitrary generated prose cannot pass validation.
REWRITES = {
    "Elaboración de reportes y tableros de seguimiento para apoyar la toma de decisiones.":
        "Elaboración de reportes y tableros de seguimiento orientados a convertir información operativa en decisiones concretas.",
    "Diseño y seguimiento de indicadores comerciales y operativos para evaluar ventas, costos, rentabilidad, inventarios y productividad.":
        "Diseño y seguimiento de KPIs comerciales y operativos para evaluar ventas, costos, rentabilidad, inventarios y productividad.",
    "Análisis de desvíos, comportamiento del negocio y causas raíz para convertir información operativa en acciones y prioridades.":
        "Análisis de desvíos y causas raíz para traducir el comportamiento del negocio en acciones y prioridades operativas.",
    "Seguimiento de resultados y rentabilidad para apoyar decisiones comerciales y operativas.":
        "Seguimiento de resultados y rentabilidad como soporte para decisiones comerciales y operativas.",
    "Diseño de consultas SQL, reportes y lógica analítica para evaluar rendimiento.":
        "Diseño de consultas SQL y lógica analítica para evaluar rendimiento y producir reportes.",
}


def rewrite_fact(fact: FactualText) -> str:
    return REWRITES.get(fact.text, fact.text)
