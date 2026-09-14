"""Tests for orchestrator get_requirements / update_requirements (Opgave 5)."""

from __future__ import annotations

import pytest

from runtime.pipeline_orchestrator import PipelineOrchestrator
from tests.pipeline.test_pipeline_integration import _FakeRuntime, YAML_SPEC

V2_SPEC = """
project_name: Demo v2
project_description: Updated requirements
requirements:
  - id: R1
    description: User can log in
    acceptance_criteria: ["GET /health returns 200"]
  - id: R2
    description: User can log out
    acceptance_criteria: ["POST /logout returns 200"]
"""


def _orch() -> PipelineOrchestrator:
    return PipelineOrchestrator(_FakeRuntime())


def test_get_requirements_returns_started_spec(orch=None):
    orch = _orch()
    wid = orch.start_pipeline(YAML_SPEC, "org-1", "creator-1")
    spec = orch.get_requirements(wid)
    assert spec["project_name"] == "Demo"
    assert spec["requirements"][0]["id"] == "R1"


def test_get_requirements_unknown_pipeline():
    with pytest.raises(ValueError, match="not found"):
        _orch().get_requirements("does-not-exist")


def test_update_requirements_in_draft_state():
    orch = _orch()
    wid = orch.start_pipeline(YAML_SPEC, "org-1", "creator-1")
    updated = orch.update_requirements(wid, V2_SPEC)
    assert updated["project_name"] == "Demo v2"
    assert len(updated["requirements"]) == 2
    assert orch.get_requirements(wid)["project_name"] == "Demo v2"


def test_update_requirements_rejects_invalid_yaml():
    orch = _orch()
    wid = orch.start_pipeline(YAML_SPEC, "org-1", "creator-1")
    before = orch.get_requirements(wid)
    with pytest.raises(ValueError):
        orch.update_requirements(wid, "project_name: [unclosed")
    # Fail-closed: spec untouched
    assert orch.get_requirements(wid) == before


def test_update_requirements_rejects_invalid_spec():
    orch = _orch()
    wid = orch.start_pipeline(YAML_SPEC, "org-1", "creator-1")
    before = orch.get_requirements(wid)
    with pytest.raises(ValueError):
        orch.update_requirements(wid, "not_a_dict: just a string")
    assert orch.get_requirements(wid) == before


def test_update_requirements_blocked_outside_draft():
    orch = _orch()
    wid = orch.start_pipeline(YAML_SPEC, "org-1", "creator-1")
    # Advance past REQUIREMENTS_DRAFT / validated via gate approval
    gate = next(g for g in orch._workflows[wid].gates if "requirements" in g.name.lower())
    orch.approve_gate(wid, gate.id, "approver-1")
    orch.advance_pipeline(wid)
    assert orch._workflows[wid].current_state.value != "requirements_validated"
    with pytest.raises(ValueError, match="requirements-gate"):
        orch.update_requirements(wid, V2_SPEC)
