from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

from ..models import Job
from .models import FactualText, MasterCV, ProjectEntry

ROLE_TAGS = {
    "pricing": ["pricing", "sales", "margins", "profitability", "costs", "commercial", "excel"],
    "business": ["business-analysis", "kpi", "reporting", "decision-making", "processes", "stakeholders", "operations"],
    "operations": ["operations", "processes", "kpi", "automation", "root-cause", "optimization"],
    "data": ["sql", "python", "power-bi", "data-quality", "analytics", "reporting"],
    "bi": ["power-bi", "dax", "sql", "excel", "data-visualization", "business-intelligence", "business-analytics", "reporting"],
    "data-science": ["python", "pandas", "numpy", "scikit-learn", "machine-learning", "sql"],
    "data-engineering": ["sql", "postgresql", "apis", "json", "jsonl", "etl", "data-ingestion", "python", "linux", "aws", "oci"],
    "cloud": ["aws", "oci", "linux", "networking", "cloud"],
    "ai-automation": ["generative-ai", "n8n", "ai-agents", "chatbots", "python", "automation"],
    "security": ["security-fundamentals", "linux", "sql", "python", "networking"],
}
TERM_TAGS = {
    "power bi": "power-bi", "kpis": "kpi", "kpi": "kpi", "procesos": "processes",
    "mejora de procesos": "processes", "process": "processes", "stakeholders": "stakeholders",
    "reporting": "reporting", "analisis comercial": "commercial", "análisis comercial": "commercial",
    "reportes": "reporting", "decisiones": "decision-making",
    "sql": "sql", "python": "python", "excel": "excel", "pricing": "pricing",
    "costos": "costs", "logistica": "logistics", "logística": "logistics", "riesgo": "risk",
    "fintech": "fintech", "quantitative": "quantitative", "churn": "churn",
    "etl": "etl", "eda": "eda", "pandas": "pandas", "numpy": "numpy",
    "machine learning": "machine-learning", "scikit-learn": "scikit-learn", "sklearn": "scikit-learn",
    "postgresql": "postgresql", "dax": "dax",
    "api rest": "apis", "apis rest": "apis", "rest api": "apis", "json": "json", "jsonl": "jsonl",
    "ingesta de datos": "data-ingestion", "data ingestion": "data-ingestion",
    "linux": "linux", "aws": "aws", "oci": "oci", "oracle cloud": "oci",
    "networking": "networking", "redes": "networking", "security": "security-fundamentals",
    "automation": "automation", "automatizacion": "automation", "automatización": "automation",
    "workflow automation": "automation", "apis": "apis", "api": "apis",
    "inteligencia artificial": "generative-ai", "ia": "generative-ai",
    "generative ai": "generative-ai", "ia generativa": "generative-ai", "n8n": "n8n",
    "ai agents": "ai-agents", "agentes ia": "ai-agents", "agentes de ia": "ai-agents",
    "chatbot": "chatbots", "chatbots": "chatbots",
}
IMPACT_TAGS = {
    "business-impact", "optimization", "costs", "profitability", "decision-making", "customers",
    "sales", "logistics", "processes", "operations", "commercial",
}
QUANT_TAGS = {"quantitative", "risk", "fintech", "trading"}


@dataclass(frozen=True, slots=True)
class Selection:
    keywords: list[str]
    explicit_tags: list[str]
    summary: list[FactualText]
    experience_facts: dict[int, list[FactualText]]
    project_facts: dict[int, list[FactualText]]
    course_indices: list[int]
    omitted_ids: list[str]


def extract_job_requirements(job: Job) -> tuple[list[str], list[str]]:
    text = _normalize(f"{job.title} {job.description}")
    families = []
    if any(term in text for term in ("data scientist", "ciencia de datos", "machine learning scientist")): families.append("data-science")
    if any(term in text for term in ("data engineer", "analytics engineer", "ingenieria de datos", "ingeniero de datos")): families.append("data-engineering")
    if any(term in text for term in ("bi analyst", "business intelligence", "analista bi")): families.append("bi")
    if any(term in text for term in ("cloud", "nube", "aws", "oci")): families.append("cloud")
    if any(term in text for term in ("ai automation", "automatizacion con ia", "agentes de ia", "n8n", "chatbot")): families.append("ai-automation")
    if any(term in text for term in ("cybersecurity", "ciberseguridad", "network security", "seguridad informatica")): families.append("security")
    if any(term in text for term in ("business", "negocio", "comercial")): families.append("business")
    if any(term in text for term in ("data", "datos", "analytics", "sql", "power bi")): families.append("data")
    if any(term in text for term in ("pricing", "precio", "margen")): families.append("pricing")
    if any(term in text for term in ("operations", "operaciones")): families.append("operations")
    if not families: families.append("data")
    explicit = _unique(tag for term, tag in TERM_TAGS.items() if _normalize(term) in text)
    return _unique([*explicit, *(tag for family in families for tag in ROLE_TAGS[family])]), explicit


def select_facts(job: Job, master: MasterCV, content_mode: str = "concise") -> Selection:
    if content_mode not in {"concise", "detailed"}:
        raise ValueError("content_mode must be concise or detailed")
    keywords, explicit = extract_job_requirements(job)
    summary = _summary_facts(master.summary_facts, keywords)
    selected_ids = {fact.id for fact in summary}
    experience: dict[int, list[FactualText]] = {}
    limits = [4, 3, 2] if content_mode == "concise" else [5, 4, 3]
    for index, entry in enumerate(master.experience):
        limit = limits[min(index, len(limits) - 1)]
        if "pricing" in keywords and any("pricing" in {_normalize_tag(tag) for tag in fact.tags} for fact in entry.facts):
            limit = max(limit, 4)
        chosen = _diverse_top([*entry.facts, *entry.achievements], keywords, limit)
        if not chosen and (entry.facts or entry.achievements):
            chosen = [*entry.facts, *entry.achievements][:1]
        if chosen:
            experience[index] = chosen
            selected_ids.update(fact.id for fact in chosen)
    projects: dict[int, list[FactualText]] = {}
    candidates = []
    for index, entry in enumerate(master.projects):
        if entry.metrics:
            chosen = [*_diverse_top(entry.facts, keywords, 1), *_diverse_top(entry.metrics, keywords, 1)]
        else:
            chosen = _diverse_top(entry.facts, keywords, 2)
        if chosen:
            candidates.append((_project_score(entry, chosen, keywords, explicit), index, chosen))
    project_limit = (2 if "pricing" in keywords else 3) if content_mode == "concise" else 5
    for _, index, chosen in sorted(candidates, key=lambda item: (-item[0], item[1]))[:project_limit]:
        projects[index] = chosen
        selected_ids.update(fact.id for fact in chosen)
    course_scores = []
    security_relevant = "security-fundamentals" in {_normalize_tag(tag) for tag in explicit}
    for index, course in enumerate(master.courses):
        if _is_security_course(course) and not security_relevant:
            continue
        score = sum(relevance_score(fact, keywords) for fact in course.facts)
        score += relevance_score(f"{course.institution} {course.program}", keywords)
        if _course_specific_match(course, job):
            score += 30
        if _is_security_course(course) and security_relevant:
            score += 12
        if score:
            course_scores.append((score, index))
    course_limit = 2 if content_mode == "concise" else 3
    ranked_courses = sorted(course_scores, key=lambda item: (-item[0], item[1]))
    threshold = ranked_courses[0][0] * 0.35 if ranked_courses else 0
    course_indices = [index for score, index in ranked_courses if score >= threshold][:course_limit]
    for index in course_indices:
        selected_ids.update(fact.id for fact in master.courses[index].facts if relevance_score(fact, keywords))
    omitted = [identifier for identifier in master.factual_ids if identifier not in selected_ids]
    return Selection(keywords, explicit, summary, experience, projects, course_indices, omitted)


def select_skills(job: Job, master: MasterCV, selection: Selection, limit: int = 12) -> list[str]:
    text = _normalize(f"{job.title} {job.description}")
    description = _normalize(job.description)
    scored = []
    role_priorities = _role_skill_priorities(job)
    for index, skill in enumerate(master.all_skills):
        skill_tag = _skill_tag(skill)
        explicit = 12 if _skill_explicit(skill, skill_tag, text, selection.explicit_tags) else 0
        adjacent_aliases = {
            "business-analytics": "business-analysis", "operations-analytics": "operations",
            "kpi-design": "kpi", "process-improvement": "processes",
            "stakeholder-management": "stakeholders", "decision-making": "decision-making",
            "sales-analysis": "sales", "profitability-analysis": "profitability",
            "cost-analysis": "costs", "customer-analysis": "customers",
            "generative-ai": "generative-ai",
        }
        keyword_tags = {_normalize_tag(tag) for tag in selection.keywords}
        adjacent = 4 if skill_tag in keyword_tags or adjacent_aliases.get(skill_tag) in keyword_tags else 0
        category = next((name for name, values in master.skills_by_category.items() if skill in values), "")
        noise_penalty = 2 if category == "technology" and not explicit else 0
        position = _explicit_position(skill, skill_tag, description)
        role_bonus = max(0, 10 - role_priorities.index(skill_tag)) if skill_tag in role_priorities else 0
        scored.append((explicit + adjacent + role_bonus - noise_penalty, position, index, skill))
    positive = [item for item in sorted(scored, key=lambda item: (-item[0], item[1], item[2])) if item[0] > 0]
    selected, seen_concepts = [], set()
    for _, _, _, skill in positive:
        concept = _skill_concept(skill)
        if concept in seen_concepts:
            continue
        selected.append(skill)
        seen_concepts.add(concept)
        if len(selected) >= limit:
            break
    return selected


def rank_skills(skills: list[str], keywords: list[str]) -> list[str]:
    return sorted(skills, key=lambda skill: (-relevance_score(skill, keywords), skills.index(skill)))


def relevance_score(value: str | FactualText, keywords: list[str]) -> int:
    text = value.text if isinstance(value, FactualText) else str(value)
    tags = {_normalize_tag(tag) for tag in value.tags} if isinstance(value, FactualText) else set()
    normalized_text = _normalize(text)
    return sum(4 if _normalize_tag(keyword) in tags else int(_keyword_in_text(keyword, normalized_text)) for keyword in keywords)


def semantic_duplicate(first: FactualText, second: FactualText) -> bool:
    first_tags = {_normalize_tag(tag) for tag in first.tags}
    second_tags = {_normalize_tag(tag) for tag in second.tags}
    if first_tags and second_tags:
        overlap = len(first_tags & second_tags) / max(1, len(first_tags | second_tags))
        if overlap >= 0.6:
            return True
    first_terms, second_terms = set(_normalize(first.text).split()), set(_normalize(second.text).split())
    return len(first_terms & second_terms) / max(1, min(len(first_terms), len(second_terms))) >= 0.72


def _summary_facts(facts: list[FactualText], keywords: list[str]) -> list[FactualText]:
    desired = ["summary_01", "summary_02", "summary_07", "summary_03", "summary_05", "summary_08"]
    if "pricing" in keywords or "commercial" in keywords:
        desired.insert(2, "summary_04")
    by_id = {fact.id: fact for fact in facts}
    selected = [by_id[identifier] for identifier in desired if identifier in by_id]
    return selected or _diverse_top(facts, keywords, 6)


def _diverse_top(facts: list[FactualText], keywords: list[str], limit: int) -> list[FactualText]:
    remaining = sorted(
        enumerate(facts),
        key=lambda item: (-(relevance_score(item[1], keywords) + _impact_score(item[1])), item[0]),
    )
    chosen: list[FactualText] = []
    for _, fact in remaining:
        if relevance_score(fact, keywords) <= 0 and not _impact_score(fact):
            continue
        if any(semantic_duplicate(fact, prior) for prior in chosen):
            continue
        chosen.append(fact)
        if len(chosen) >= limit:
            break
    return chosen


def _project_score(entry: ProjectEntry, facts: list[FactualText], keywords: list[str], explicit: list[str]) -> int:
    score = sum(relevance_score(fact, keywords) + _impact_score(fact) for fact in facts)
    score += relevance_score(f"{entry.category} {' '.join(entry.technologies)}", keywords)
    score += len(entry.metrics) * 5
    entry_tags = {_normalize_tag(tag) for fact in [*entry.facts, *entry.metrics] for tag in fact.tags}
    technology_tags = {_normalize_tag(technology) for technology in entry.technologies}
    score += 4 * len(technology_tags & {_normalize_tag(tag) for tag in explicit})
    score += 3 * len(entry_tags & IMPACT_TAGS)
    if entry_tags & QUANT_TAGS and not ({_normalize_tag(tag) for tag in explicit} & QUANT_TAGS):
        score -= 12
    return score


def _impact_score(fact: FactualText) -> int:
    tags = {_normalize_tag(tag) for tag in fact.tags}
    metric_bonus = 4 if fact.kind == "metric" else 0
    quantified = 3 if re.search(r"\d", fact.text) else 0
    economic = 4 if any(term in _normalize(fact.text) for term in ("ahorro", "cost", "ingreso", "revenue")) else 0
    return metric_bonus + quantified + economic + 2 * len(tags & IMPACT_TAGS)


def _keyword_in_text(keyword: str, text: str) -> bool:
    aliases = {
        "generative-ai": ("inteligencia artificial", " ia ", "agentes de ia", "generative ai"),
        "reporting": ("reporting", "reporte", "reportes"),
        "decision-making": ("decision", "decisiones"),
        "processes": ("proceso", "procesos"),
        "automation": ("automation", "automatizacion", "automatización", "workflow automation"),
        "apis": ("api", "apis"),
        "data-ingestion": ("ingesta de datos", "data ingestion", "ingestion"),
        "security-fundamentals": ("security", "seguridad", "cybersecurity", "ciberseguridad"),
        "ai-agents": ("ai agents", "agentes ia", "agentes de ia"),
        "chatbots": ("chatbot", "chatbots"),
    }
    terms = aliases.get(_normalize_tag(keyword), (_tag_text(keyword),))
    padded = f" {text} "
    return any(term in padded for term in terms)


def _skill_explicit(skill: str, tag: str, text: str, explicit_tags: list[str]) -> bool:
    aliases = {
        "kpi-design": "kpi", "business-analytics": "business", "business-analysis": "business",
        "process-improvement": "processes", "stakeholder-management": "stakeholders",
        "operations-analytics": "operations", "decision-making": "decision-making",
    }
    return _normalize(skill) in text or tag in {_normalize_tag(value) for value in explicit_tags} or aliases.get(tag) in explicit_tags


def _explicit_position(skill: str, tag: str, description: str) -> int:
    terms = {
        "kpi-design": ["kpi", "kpis"], "process-improvement": ["procesos", "process"],
        "stakeholder-management": ["stakeholder"], "business-analysis": ["analisis comercial", "business analysis"],
        "business-analytics": ["analisis comercial", "business analytics"],
    }.get(tag, [_normalize(skill), tag.replace("-", " ")])
    positions = [description.find(_normalize(term)) for term in terms if description.find(_normalize(term)) >= 0]
    return min(positions) if positions else 10_000


def _skill_tag(skill: str) -> str:
    aliases = {"apis-rest": "apis", "ingesta-de-datos": "data-ingestion"}
    normalized = _normalize_tag(skill)
    return aliases.get(normalized, normalized)


def _skill_concept(skill: str) -> str:
    tag = _skill_tag(skill)
    return "apis" if tag in {"apis", "api"} else tag


def _role_skill_priorities(job: Job) -> list[str]:
    text = _normalize(f"{job.title} {job.description}")
    families = []
    patterns = (
        ("pricing", ("pricing", "precios", "margenes", "rentabilidad")),
        ("business", ("business analyst", "analista de negocios", "business analysis", "stakeholders", "kpi")),
        ("operations", ("operations analyst", "analista de operaciones", "process improvement", "mejora de procesos")),
        ("data-science", ("data scientist", "ciencia de datos", "scikit-learn", "machine learning")),
        ("data-engineering", ("data engineer", "analytics engineer", "ingenieria de datos", "etl", "data pipeline")),
        ("bi", ("bi analyst", "business intelligence", "analista bi", "power bi", "dax")),
        ("ai-automation", ("ai automation", "workflow automation", "automatizacion con ia", "n8n", "chatbot", "ai agents", "agentes de ia")),
        ("cloud", ("cloud", "nube", "aws", "oci")),
        ("security", ("cybersecurity", "ciberseguridad", "network security", "seguridad informatica")),
    )
    for family, terms in patterns:
        if any(term in text for term in terms):
            families.append(family)
    if not families or any(term in text for term in ("data analyst", "analista de datos", "analytics")):
        families.append("data")
    return _unique(tag for family in families for tag in ROLE_TAGS[family])


def _is_security_course(course) -> bool:
    identity = _normalize(f"{course.institution} {course.program}")
    return "cybersecurity" in identity or "ciberseguridad" in identity


def _course_specific_match(course, job: Job) -> bool:
    job_terms = re.findall(r"[a-z0-9+#]+", _normalize(job.description))
    course_text = _normalize(" ".join([course.program, *(fact.text for fact in course.facts)]))
    course_terms = re.findall(r"[a-z0-9+#]+", course_text)
    job_pairs = {tuple(job_terms[index:index + 2]) for index in range(len(job_terms) - 1)}
    course_pairs = {tuple(course_terms[index:index + 2]) for index in range(len(course_terms) - 1)}
    generic = {"data", "datos", "python", "sql", "analytics", "analitica", "analisis", "con", "and", "para", "the", "y"}
    return any(any(len(term) >= 4 and term not in generic for term in pair) for pair in job_pairs & course_pairs)


def _tag_text(tag: str) -> str:
    return _normalize(tag.replace("-", " "))


def _normalize_tag(value: str) -> str:
    return _normalize(value).replace(" ", "-")


def _normalize(value: str) -> str:
    value = unicodedata.normalize("NFKD", value.lower())
    return re.sub(r"\s+", " ", "".join(character for character in value if not unicodedata.combining(character))).strip()


def _unique(values) -> list[str]:
    return list(dict.fromkeys(values))
