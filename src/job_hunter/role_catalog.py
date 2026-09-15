from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

RoleFamily = Literal["core", "strong_expansion", "exploratory"]


@dataclass(frozen=True, slots=True)
class RoleDefinition:
    canonical_title: str
    family: RoleFamily
    aliases: tuple[str, ...] = ()
    search_enabled: bool = True

    @property
    def all_titles(self) -> tuple[str, ...]:
        return (self.canonical_title, *self.aliases)


# Order is intentional: core roles are queried first and exploratory roles last.
ROLE_CATALOG: tuple[RoleDefinition, ...] = (
    RoleDefinition("Data Analyst", "core", ("Analista de Datos", "Analista de Información", "Junior Data Analyst", "Jr Data Analyst")),
    RoleDefinition("BI Analyst", "core", ("Analista BI", "Analista de BI")),
    RoleDefinition("Business Intelligence Analyst", "core", ("Analista de Business Intelligence", "Analista de Inteligencia de Negocio")),
    RoleDefinition("Business Analyst", "core", ("Analista de Negocio", "Analista de Negocios", "Analista Funcional", "Functional Analyst")),
    RoleDefinition("Operations Analyst", "core", ("Analista de Operaciones",)),
    RoleDefinition("Reporting Analyst", "core", ("Analista de Reporting", "Analista de Reportes", "Data & Reporting Analyst")),
    RoleDefinition("Analytics Analyst", "core", ("Analista de Analytics", "Insights Analyst")),
    RoleDefinition("Commercial Analyst", "core", ("Analista Comercial",)),
    RoleDefinition("Pricing Analyst", "core", ("Analista de Precios", "Analista de Pricing")),
    RoleDefinition("Business Analytics Analyst", "strong_expansion", ("Analista de Business Analytics", "Analista de Analítica de Negocio")),
    RoleDefinition("Process Analyst", "strong_expansion", ("Analista de Procesos", "Business Process Analyst")),
    RoleDefinition("Performance Analyst", "strong_expansion", ("Analista de Performance", "Analista de Rendimiento")),
    RoleDefinition("Commercial Data Analyst", "strong_expansion", ("Analista de Datos Comerciales",)),
    RoleDefinition("Sales Analyst", "strong_expansion", ("Analista de Ventas",)),
    RoleDefinition("Data & Operations Analyst", "strong_expansion", ("Data and Operations Analyst", "Analista de Datos y Operaciones")),
    RoleDefinition("Data Quality Analyst", "strong_expansion", ("Analista de Calidad de Datos",)),
    RoleDefinition("Product Data Analyst", "strong_expansion", ("Analista de Datos de Producto",)),
    RoleDefinition("Product Analyst", "strong_expansion", ("Analista de Producto",)),
    RoleDefinition("Decision Intelligence Analyst", "exploratory", ("Analista de Inteligencia de Decisiones",)),
    RoleDefinition("Automation Analyst", "exploratory", ("Analista de Automatización",)),
    RoleDefinition("Business Automation Analyst", "exploratory", ("Analista de Automatización de Negocio",)),
    RoleDefinition("AI Automation Analyst", "exploratory", ("Analista de Automatización con IA",)),
    RoleDefinition("AI Automation Engineer", "exploratory", ("AI Automation Engineer Jr", "Junior AI Automation Engineer", "Ingeniero Junior de Automatización con IA")),
    RoleDefinition("Data Scientist", "exploratory", ("Junior Data Scientist", "Data Scientist Jr", "Científico de Datos Junior", "Científica de Datos Junior")),
    RoleDefinition("Data Science Analyst", "exploratory", ("Analista de Ciencia de Datos",)),
    RoleDefinition("Data Operations Analyst", "exploratory", ("Analista de Operaciones de Datos",)),
    RoleDefinition("DataOps Analyst", "exploratory", ("DataOps Analyst Jr", "Junior DataOps Analyst", "Analista DataOps Junior")),
    RoleDefinition("Machine Learning Analyst", "exploratory", ("Junior Machine Learning Analyst", "Machine Learning Analyst Jr", "Analista Junior de Machine Learning")),
    RoleDefinition("ML Analyst", "exploratory", ("Machine Learning Analyst", "Analista de ML")),
    RoleDefinition("Analytics Consultant", "exploratory", ("Consultor de Analytics", "Consultora de Analytics")),
    RoleDefinition("BI Consultant", "exploratory", ("Junior BI Consultant", "Consultor BI Junior", "Consultora BI Junior", "BI Consultant Jr")),
)


def discovery_titles() -> list[str]:
    return [title for role in ROLE_CATALOG if role.search_enabled for title in role.all_titles]
