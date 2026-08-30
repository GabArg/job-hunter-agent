from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable

# One canonical vocabulary shared by normalization, scoring, discovery and UI.
CONCEPT_ALIASES: dict[str, tuple[str, ...]] = {
    "data-analysis": ("data analysis", "análisis de datos", "analisis de datos", "análisis de información", "analisis de informacion"),
    "business-analysis": ("business analysis", "análisis de negocios", "analisis de negocios", "análisis funcional", "analisis funcional"),
    "business-intelligence": ("business intelligence", "inteligencia de negocios", "inteligencia empresarial", "bi"),
    "reporting": ("reporting", "reportes", "informes", "generación de informes", "generacion de informes"),
    "dashboard": ("dashboard", "dashboards", "tablero", "tableros", "tablero de control"),
    "pricing": ("pricing", "precios", "análisis de precios", "analisis de precios", "estrategia de precios", "gestión de precios", "gestion de precios"),
    "profitability": ("profitability", "rentabilidad", "margen", "márgenes", "margenes"),
    "sales-analysis": ("sales analysis", "análisis de ventas", "analisis de ventas"),
    "cost-analysis": ("cost analysis", "análisis de costos", "analisis de costos", "costes", "costos"),
    "process-improvement": ("process improvement", "mejora de procesos", "optimización de procesos", "optimizacion de procesos"),
    "stakeholders": ("stakeholder", "stakeholders", "áreas de negocio", "areas de negocio", "usuarios internos", "interlocutores"),
    "requirements": ("requirements", "requerimientos", "requisitos", "relevamiento de requerimientos", "relevamiento funcional"),
    "functional-documentation": ("documentación funcional", "documentacion funcional", "functional documentation", "documentar las diferentes características"),
    "user-stories": ("user stories", "user story", "historias de usuario", "historia de usuario"),
    "backlog": ("backlog", "product backlog"), "uml": ("uml", "unified modeling language"),
    "agile": ("agile", "ágil", "agil", "scrum", "metodologías ágiles", "metodologias agiles", "marco ágil", "marco agil"),
    "product-owner": ("product owner", "po"), "slicing": ("slicing", "functional slicing"),
    "story-mapping": ("story mapping", "user story mapping", "mapa de historias"),
    "impact-mapping": ("impact mapping",),
    "service-testing": ("service testing", "api testing", "testing de servicios", "testearlos", "pruebas de servicios"),
    "system-architecture": ("system architecture", "arquitectura de sistemas", "arquitectura de un sistema", "arquitectura de software"),
    "negotiation": ("negotiation", "negociación", "negociacion", "negociando"),
    "excel": ("excel", "microsoft excel"), "power-bi": ("power bi", "powerbi"), "dax": ("dax",),
    "sql": ("sql",), "python": ("python",), "pandas": ("pandas",), "numpy": ("numpy",),
    "scikit-learn": ("scikit-learn", "scikit learn", "sklearn"), "machine-learning": ("machine learning",),
    "postgresql": ("postgresql", "postgres"), "json": ("json",), "jsonl": ("jsonl",),
    "etl": ("etl",), "data-ingestion": ("data ingestion", "ingesta de datos"),
    "linux": ("linux",), "aws": ("aws", "amazon web services"), "oci": ("oci", "oracle cloud infrastructure"),
    "networking": ("networking", "redes"), "security-fundamentals": ("security fundamentals", "fundamentos de seguridad"),
    "generative-ai": ("generative ai", "generative artificial intelligence", "inteligencia artificial", "ia", "ia generativa"),
    "automation": ("automation", "automatización", "automatizacion", "workflow automation"),
    "apis": ("api", "apis", "rest api", "apis rest"), "n8n": ("n8n",),
    "ai-agents": ("ai agents", "agentes de ia", "agentes ia"), "chatbots": ("chatbot", "chatbots"),
    "tableau": ("tableau",), "snowflake": ("snowflake",), "dbt": ("dbt",),
}

ROLE_ALIASES: dict[str, tuple[str, ...]] = {
    "data-analyst": ("data analyst", "analista de datos", "analista de información", "analista de informacion", "reporting analyst", "analista de reporting"),
    "business-analyst": ("business analyst", "analista de negocios"),
    "business-analyst-functional": ("analista funcional", "functional analyst"),
    "business-analyst-operations": ("analista de procesos", "business process analyst"),
    "pricing-analyst": ("pricing analyst", "analista de pricing", "analista de precios"),
    "commercial-analyst": ("analista comercial", "commercial analyst"),
    "operations-analyst": ("operations analyst", "analista de operaciones", "analista de procesos"),
    "bi-analyst": ("bi analyst", "business intelligence analyst", "analista bi", "analista de business intelligence"),
}

DISPLAY_NAMES = {concept: concept.replace("-", " ").title() for concept in CONCEPT_ALIASES}
DISPLAY_NAMES.update({"uml": "UML", "sql": "SQL", "apis": "APIs", "power-bi": "Power BI", "product-owner": "Product Owner"})
CAPABILITY_IMPLICATIONS = {"business-analysis": {"requirements", "stakeholders"}}


def normalize_semantic_text(value: str) -> str:
    decomposed = unicodedata.normalize("NFKD", value or "")
    plain = "".join(character for character in decomposed if not unicodedata.combining(character)).casefold()
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9+#./ -]", " ", plain)).strip()


def detect_concepts(text: str, catalog: dict[str, tuple[str, ...]] = CONCEPT_ALIASES) -> list[str]:
    normalized = normalize_semantic_text(text)
    return [concept for concept, aliases in catalog.items() if any(_phrase(normalized, alias) for alias in aliases)]


def canonicalize_terms(values: Iterable[str]) -> set[str]:
    result: set[str] = set()
    for value in values:
        detected = detect_concepts(str(value))
        result.update(detected or [normalize_semantic_text(str(value)).replace(" ", "-")])
    return result


def expand_candidate_capabilities(values: Iterable[str]) -> set[str]:
    capabilities = canonicalize_terms(values)
    for skill in tuple(capabilities): capabilities.update(CAPABILITY_IMPLICATIONS.get(skill, set()))
    return capabilities


def build_candidate_capabilities(master_cv) -> dict[str, list[str]]:
    """Build auditable canonical capabilities exclusively from factual master data."""
    evidence: dict[str, list[str]] = {}

    def add(concept: str, source_id: str) -> None:
        sources = evidence.setdefault(concept, [])
        if source_id not in sources:
            sources.append(source_id)

    for skill in master_cv.all_skills:
        for concept in canonicalize_terms([skill]):
            add(concept, f"skill:{skill}")
    for identifier, value in master_cv.fact_index.items():
        text = getattr(value, "text", None)
        if text is None:
            continue
        concepts = set(detect_concepts(text))
        concepts.update(canonicalize_terms(getattr(value, "tags", ())))
        for concept in concepts:
            add(concept, identifier)
    for experience in master_cv.experience:
        for technology in experience.technologies:
            for concept in canonicalize_terms([technology]):
                add(concept, f"{experience.id}:technology:{technology}")
    for project in master_cv.projects:
        for technology in project.technologies:
            for concept in canonicalize_terms([technology]):
                add(concept, f"{project.id}:technology:{technology}")
    for concept in tuple(evidence):
        for implied in CAPABILITY_IMPLICATIONS.get(concept, set()):
            for source_id in evidence[concept]:
                add(implied, source_id)
    return evidence


def detect_roles(title: str, description: str = "") -> set[str]:
    roles = {
        concept for concept, aliases in ROLE_ALIASES.items()
        if any(_role_alias_matches(title, alias) for alias in aliases)
    }
    requirements = set(detect_concepts(description))
    if "commercial-analyst" in roles and requirements & {"pricing", "profitability", "sales-analysis", "cost-analysis"}:
        roles.add("pricing-analyst")
    if roles & {"business-analyst", "business-analyst-functional", "business-analyst-operations"}:
        if requirements & {"user-stories", "backlog", "product-owner", "story-mapping"}: roles.add("business-analyst-product")
        if requirements & {"requirements", "functional-documentation", "uml", "service-testing"}: roles.add("business-analyst-functional")
        if requirements & {"process-improvement", "reporting", "dashboard"}: roles.add("business-analyst-operations")
        if requirements & {"sql", "python", "power-bi", "data-analysis", "business-intelligence"}: roles.add("business-analyst-data")
    return roles


def roles_match(title: str, target: str, description: str = "") -> bool:
    actual, desired = detect_roles(title, description), detect_roles(target)
    if actual & desired: return True
    business_family = {"business-analyst", "business-analyst-functional", "business-analyst-operations", "business-analyst-product", "business-analyst-data"}
    return bool(actual & business_family and desired & business_family)


def expand_target_roles(roles: Iterable[str]) -> list[str]:
    expanded: list[str] = []
    for role in roles:
        canonical = detect_concepts(role, ROLE_ALIASES)
        aliases = [alias for concept in canonical for alias in ROLE_ALIASES[concept]]
        expanded.extend(aliases or [role])
        if "business-analyst" in canonical: expanded.extend((*ROLE_ALIASES["business-analyst-functional"], *ROLE_ALIASES["business-analyst-operations"]))
        if "pricing-analyst" in canonical: expanded.extend(ROLE_ALIASES["commercial-analyst"])
    return list(dict.fromkeys(expanded))


def display_concepts(concepts: Iterable[str]) -> list[str]:
    return [DISPLAY_NAMES.get(value, value.replace("-", " ").title()) for value in concepts]


def _phrase(text: str, phrase: str) -> bool:
    value = normalize_semantic_text(phrase)
    return bool(value and re.search(rf"(?<![a-z0-9]){re.escape(value)}(?![a-z0-9])", text))


def _role_alias_matches(title: str, alias: str) -> bool:
    stop = {"de", "del", "y", "and", "junior", "jr", "semi", "senior", "ssr", "sr"}
    title_tokens = set(normalize_semantic_text(title).replace("-", " ").split()) - stop
    alias_tokens = set(normalize_semantic_text(alias).replace("-", " ").split()) - stop
    return bool(alias_tokens and alias_tokens <= title_tokens)
