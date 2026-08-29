from __future__ import annotations

import hashlib
import shutil
from pathlib import Path

import pytest
import yaml

from job_hunter.cv import adapt_cv, load_master_cv
from job_hunter.knowledge import KnowledgeUpdater, ProposalGenerator, ProposalStatus
from job_hunter.knowledge.audit import AuditLog
from job_hunter.knowledge.validator import validate_proposal
from job_hunter.models import Job

REAL_MASTER = Path("private/master_cv.yaml")


def setup_updater(tmp_path, consistency_check=None):
    master = tmp_path / "master_cv.yaml"
    shutil.copy2(REAL_MASTER, master)
    kwargs = {} if consistency_check is None else {"consistency_check": consistency_check}
    updater = KnowledgeUpdater(master, tmp_path / "proposals.yaml", tmp_path / "audit.jsonl", tmp_path / "backups", **kwargs)
    return updater, master


def course_entry(**overrides):
    value = {
        "type": "COURSE", "title": "Advanced Analytics Demo", "institution": "Example Academy",
        "program": "Advanced Analytics Demo", "status": "completed", "skills": ["Azure SQL", "SQL"],
        "evidence": ["manual_confirmation"], "fact": "Curso completado de analítica avanzada con Azure SQL.",
    }
    value.update(overrides)
    return value


def create_validate_approve(updater, master, entry=None):
    proposal = updater.create(ProposalGenerator().generate(entry or course_entry(), master))
    updater.validate(proposal.id)
    updater.approve(proposal.id)
    return proposal.id


def test_valid_course_proposal(tmp_path):
    updater, master = setup_updater(tmp_path)
    proposal = updater.create(ProposalGenerator().generate(course_entry(), master))
    assert updater.validate(proposal.id).status == ProposalStatus.PENDING_APPROVAL


def test_ongoing_course_is_not_validated_as_completed(tmp_path):
    updater, master = setup_updater(tmp_path)
    proposal = ProposalGenerator().generate(course_entry(status="en curso"), master)
    result = validate_proposal(proposal, master)
    assert result.status == ProposalStatus.DRAFT
    assert any("completed" in error for error in result.validation_errors)


def test_project_update_existing_project(tmp_path):
    updater, master = setup_updater(tmp_path)
    entry = {"type": "PROJECT_UPDATE", "project": "NodoScouting", "title": "Demo", "fact": "Hecho de prueba local.", "tags": ["analytics"], "evidence": ["github_commit"]}
    proposal = updater.create(ProposalGenerator().generate(entry, master))
    assert updater.validate(proposal.id).status == ProposalStatus.PENDING_APPROVAL


def test_project_update_missing_project_fails(tmp_path):
    _, master = setup_updater(tmp_path)
    with pytest.raises(ValueError, match="Target not found"):
        ProposalGenerator().generate({"type": "PROJECT_UPDATE", "project": "Missing", "fact": "x", "evidence": ["github_commit"]}, master)


def test_project_proposal_preserves_multiple_facts_and_links(tmp_path):
    _, master = setup_updater(tmp_path)
    proposal = ProposalGenerator().generate({
        "type": "PROJECT", "title": "Repository Project", "category": "Analytics",
        "facts": ["Primer hecho.", "Segundo hecho."], "technologies": ["Python"],
        "links": ["https://example.test/repo"], "evidence": ["github_repo"],
    }, master)
    value = proposal.proposed_changes["value"]
    assert value["name"] == "Repository Project"
    assert [fact["id"] for fact in value["facts"]] == [f'{value["id"]}_fact_01', f'{value["id"]}_fact_02']
    assert value["links"] == ["https://example.test/repo"]


def test_skill_without_evidence_fails(tmp_path):
    _, master = setup_updater(tmp_path)
    proposal = ProposalGenerator().generate({"type": "SKILL", "title": "Demo Skill", "skill": "Demo Skill", "category": "technology"}, master)
    assert validate_proposal(proposal, master).status == ProposalStatus.DRAFT


def test_generated_ids_do_not_collide(tmp_path):
    _, master = setup_updater(tmp_path)
    current = load_master_cv(master)
    proposal = ProposalGenerator().generate(course_entry(), master)
    ids = {proposal.proposed_changes["value"]["id"], proposal.proposed_changes["value"]["facts"][0]["id"]}
    assert not ids & set(current.fact_index)


def test_approve_does_not_modify_master(tmp_path):
    updater, master = setup_updater(tmp_path); before = master.read_bytes()
    create_validate_approve(updater, master)
    assert master.read_bytes() == before


def test_apply_requires_approved(tmp_path):
    updater, master = setup_updater(tmp_path)
    proposal = updater.create(ProposalGenerator().generate(course_entry(), master))
    with pytest.raises(ValueError, match="APPROVED"): updater.apply(proposal.id)


def test_apply_creates_backup_and_modifies_master(tmp_path):
    updater, master = setup_updater(tmp_path); proposal_id = create_validate_approve(updater, master)
    updater.apply(proposal_id)
    assert list((tmp_path / "backups").glob("master_cv_*.yaml"))
    assert any(course.program == "Advanced Analytics Demo" for course in load_master_cv(master).courses)


def test_rollback_restores_original_master(tmp_path):
    def fail(_): raise ValueError("post-write validation failure")
    updater, master = setup_updater(tmp_path, fail); before = master.read_bytes()
    proposal_id = create_validate_approve(updater, master)
    with pytest.raises(ValueError, match="post-write"): updater.apply(proposal_id)
    assert master.read_bytes() == before
    assert AuditLog(tmp_path / "audit.jsonl").events()[-1]["action"] == "ROLLBACK"


def test_audit_records_lifecycle(tmp_path):
    updater, master = setup_updater(tmp_path); proposal_id = create_validate_approve(updater, master)
    updater.apply(proposal_id)
    assert [event["action"] for event in updater.audit.events()] == ["CREATE", "VALIDATE", "APPROVE", "APPLY"]


def test_reject_does_not_modify_master(tmp_path):
    updater, master = setup_updater(tmp_path); before = master.read_bytes()
    proposal = updater.create(ProposalGenerator().generate(course_entry(), master)); updater.reject(proposal.id)
    assert master.read_bytes() == before


def test_duplicate_proposal_is_detected(tmp_path):
    updater, master = setup_updater(tmp_path); proposal = ProposalGenerator().generate(course_entry(), master)
    updater.create(proposal)
    with pytest.raises(ValueError, match="Duplicate"): updater.create(ProposalGenerator().generate(course_entry(), master))


def test_cv_agent_sees_applied_course(tmp_path):
    updater, master = setup_updater(tmp_path); proposal_id = create_validate_approve(updater, master); updater.apply(proposal_id)
    loaded = load_master_cv(master)
    job = Job("Data Analyst", "Example", "Argentina", "Remote", "Azure SQL analytics", "test", "https://example.test/job", score=80, decision="APPLY")
    adapted = adapt_cv(job, loaded)
    assert any(course.program == "Advanced Analytics Demo" for course in adapted.courses)


def test_cv_agent_accepts_new_project_fact_source_id(tmp_path):
    updater, master = setup_updater(tmp_path)
    entry = {"type": "PROJECT_UPDATE", "project": "Business Intelligence & Automatización", "title": "Pricing demo", "fact": "Análisis de pricing y costos para decisiones comerciales.", "tags": ["pricing", "costs", "commercial"], "evidence": ["github_commit"]}
    proposal = updater.create(ProposalGenerator().generate(entry, master)); new_id = proposal.proposed_changes["value"]["id"]
    updater.validate(proposal.id); updater.approve(proposal.id); updater.apply(proposal.id)
    job = Job("Pricing Analyst", "Example", "Argentina", "Hybrid", "pricing costos comercial Excel reporting", "test", "https://example.test/pricing", score=80, decision="APPLY")
    adapted = adapt_cv(job, load_master_cv(master))
    used = {identifier for section in adapted.project_sections for bullet in section.bullets for identifier in bullet.source_fact_ids}
    assert new_id in load_master_cv(master).fact_index
    assert new_id in used


def test_real_master_is_preserved_when_temporary_apply_fails(tmp_path):
    real_before = hashlib.sha256(REAL_MASTER.read_bytes()).hexdigest()
    def fail(_): raise RuntimeError("forced")
    updater, master = setup_updater(tmp_path, fail); proposal_id = create_validate_approve(updater, master)
    with pytest.raises(RuntimeError): updater.apply(proposal_id)
    assert hashlib.sha256(REAL_MASTER.read_bytes()).hexdigest() == real_before
