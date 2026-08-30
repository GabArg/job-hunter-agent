from __future__ import annotations

from job_hunter.cv.adapter import adapt_cv
from job_hunter.cv.loader import load_master_cv
from job_hunter.cv.selector import ROLE_TAGS, _term_matches, extract_job_requirements
from job_hunter.models import Job


MASTER_PATH = "private/master_cv.yaml"


def _adapt(title: str, description: str):
    job = Job(
        title, "Example", "Argentina", "remote", description, "test",
        f"https://example.com/{title.lower().replace(' ', '-')}", score=70, decision="REVIEW",
    )
    return adapt_cv(job, load_master_cv(MASTER_PATH))


def test_master_training_inventory_is_available_without_duplicates():
    master = load_master_cv(MASTER_PATH)
    expected = {
        "Python", "SQL", "Pandas", "NumPy", "Scikit-learn", "Machine Learning",
        "Power BI", "DAX", "Excel", "Data Visualization", "PostgreSQL", "APIs REST",
        "JSON", "JSONL", "ETL", "Ingesta de datos", "AWS", "OCI", "Linux", "Git",
        "GitHub", "Generative AI", "n8n", "AI Agents", "Chatbots", "Automation",
    }
    assert expected <= set(master.all_skills)
    assert len(master.all_skills) == len(set(master.all_skills))


def test_new_course_facts_are_indexed_with_stable_unique_ids():
    master = load_master_cv(MASTER_PATH)
    expected = {
        "course_01_fact_03", "course_03_fact_02", "course_05_fact_02",
        "course_05_fact_03", "course_06_fact_01", "course_06_fact_02",
    }
    assert expected <= set(master.fact_index)
    assert len(master.fact_index) == len(set(master.fact_index))


def test_data_engineering_prioritizes_integration_and_cloud_skills():
    cv = _adapt(
        "Data Engineer",
        "SQL, PostgreSQL, APIs REST, JSON, JSONL, ETL, ingesta de datos, Python, Linux y AWS.",
    )
    assert cv.skills[:8] == ["SQL", "PostgreSQL", "APIs REST", "JSON", "JSONL", "ETL", "Ingesta de datos", "Python"]
    assert "AWS re/Start" in {course.program for course in cv.courses}


def test_data_science_prioritizes_scientific_stack():
    cv = _adapt(
        "Data Scientist",
        "Python, Pandas, NumPy, Scikit-learn, Machine Learning y SQL.",
    )
    assert cv.skills[:6] == ["Python", "Pandas", "NumPy", "Scikit-learn", "Machine Learning", "SQL"]


def test_ai_automation_selects_focused_training_and_skills():
    cv = _adapt(
        "AI Automation Analyst",
        "Generative AI, n8n, AI Agents, Chatbots, Python y Automation.",
    )
    assert cv.skills[:6] == ["Generative AI", "n8n", "AI Agents", "Chatbots", "Python", "Automation"]
    assert [course.program for course in cv.courses] == ["Transformación Digital con IA y Automatización"]


def test_cybersecurity_course_is_never_selected_automatically():
    data_cv = _adapt("Data Analyst", "SQL, Python, Power BI, Excel y reporting.")
    security_cv = _adapt("Cybersecurity Analyst", "Linux, SQL, Python, networking y security fundamentals.")
    assert "Cybersecurity" not in {course.program for course in data_cv.courses}
    assert "Cybersecurity" not in {course.program for course in security_cv.courses}


def test_concise_cv_limits_courses_and_avoids_api_skill_duplicates():
    cv = _adapt("Data Analyst", "SQL, Python, Power BI, PostgreSQL, APIs REST y JSON.")
    assert len(cv.courses) <= 2
    assert not ({"APIs", "APIs REST"} <= set(cv.skills))


def test_short_aliases_use_word_boundaries():
    assert not _term_matches("ia", "IAM y cloud security")
    assert _term_matches("ia", "soluciones de IA generativa")
    assert _term_matches("bi", "BI Analyst")
    assert not _term_matches("bi", "bilingual analyst")
    assert _term_matches("ai", "AI Agents")
    assert not _term_matches("ai", "email automation")


def test_iam_does_not_detect_generative_ai_but_real_ia_does():
    iam_job = Job("Cloud Data Engineer", "Example", "Argentina", "remote", "AWS, IAM y Linux", "test", "https://example.com/iam")
    ai_job = Job("Automation Analyst", "Example", "Argentina", "remote", "Soluciones de IA generativa", "test", "https://example.com/ia")
    assert "generative-ai" not in extract_job_requirements(iam_job)[1]
    assert "generative-ai" in extract_job_requirements(ai_job)[1]


def test_data_engineering_only_includes_power_bi_when_explicit():
    without_bi = _adapt("Data Engineer", "SQL PostgreSQL APIs REST JSON JSONL ETL ingesta Python Linux AWS")
    with_bi = _adapt("Data Engineer", "SQL PostgreSQL ETL Python y Power BI")
    assert "Power BI" not in without_bi.skills
    assert "Power BI" in with_bi.skills


def test_data_science_only_includes_power_bi_when_explicit():
    without_bi = _adapt("Data Scientist", "Python Pandas NumPy Scikit-learn Machine Learning SQL estadística")
    with_bi = _adapt("Data Scientist", "Python Pandas Machine Learning SQL y Power BI")
    assert "Power BI" not in without_bi.skills
    assert "Reporting" not in without_bi.skills
    assert "Power BI" in with_bi.skills


def test_ai_automation_remains_focused_and_valid():
    cv = _adapt("AI Automation Analyst", "Generative AI n8n AI Agents Chatbots Python APIs Automation")
    assert cv.skills[:6] == ["Generative AI", "n8n", "AI Agents", "Chatbots", "Python", "Automation"]
    assert cv.validation_status == "VALID"


def test_security_is_not_an_active_role_family():
    assert "security" not in ROLE_TAGS


def test_google_security_training_is_excluded_from_target_families():
    cases = (
        ("Data Analyst", "SQL Python Power BI"),
        ("BI Analyst", "Power BI DAX SQL Excel"),
        ("Data Scientist", "Python Pandas Scikit-learn Machine Learning"),
        ("AI Automation Analyst", "Generative AI n8n AI Agents Chatbots"),
        ("Cloud Data Engineer", "AWS Linux networking security fundamentals SQL Python"),
    )
    for title, description in cases:
        cv = _adapt(title, description)
        assert "Cybersecurity" not in {course.program for course in cv.courses}
        assert cv.validation_status == "VALID"
