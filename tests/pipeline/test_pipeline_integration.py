"""Tests for the pipeline integration + gate approval flow (Opgave 3 & 4)."""

from __future__ import annotations

import pytest

from execution.pipeline_executors import (
    PipelineExecutorConfigurationError,
    build_pipeline_executor_registry,
)
from runtime.pipeline_orchestrator import PipelineOrchestrator
from runtime.pipeline_state_store import PipelineStateStore
from services.task_execution_service import DictTaskExecutorFactory


class _FakeRuntime:
    """Duck-type of DORRuntime core signature used by the orchestrator."""

    def __init__(self) -> None:
        self.workflows: dict = {}

    def get_workflow(self, context, workflow_id):
        return self.workflows.get(workflow_id)

    def create_workflow(self, context, name, description=""):
        return None

    def transition_workflow(self, context, workflow_id, new_state, evidence=None):
        wf = self.workflows.get(workflow_id)
        if wf is not None:
            wf.current_state = new_state
        return wf


YAML_SPEC = """
project_name: Demo
project_description: A demo pipeline
requirements:
  - id: R1
    description: User can log in
    acceptance_criteria: ["Login works"]
"""


@pytest.fixture()
def orch():
    return PipelineOrchestrator(_FakeRuntime())


class _FakeStructuredGenerator:
    def generate(self, prompt, schema):
        if "architecture" in prompt:
            return {
                "services": [],
                "components": [],
                "data_models": [],
                "decisions": [],
            }
        if "contracts" in prompt:
            return {"openapi": {}, "asyncapi": {}}
        return {"files": []}


def test_pipeline_executor_registry_covers_all_states(orch):
    registry = build_pipeline_executor_registry(_FakeStructuredGenerator())
    for task_type in [
        "generate_architecture",
        "generate_contracts",
        "generate_code",
        "generate_tests",
        "run_tests",
        "deploy",
        "release",
    ]:
        assert task_type in registry, f"missing executor: {task_type}"
    for task_type in [
        "generate_architecture",
        "generate_contracts",
        "generate_code",
        "generate_tests",
        "release",
    ]:
        assert registry[task_type].execute({"name": "demo"})["status"] == "success"


def test_pipeline_ai_executor_fails_closed_without_configuration(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("DOR_PIPELINE_MODEL", raising=False)
    with pytest.raises(PipelineExecutorConfigurationError):
        build_pipeline_executor_registry()["generate_architecture"].execute({})


def test_pipeline_starts_and_blocks_at_requirements_gate(orch):
    wid = orch.start_pipeline(YAML_SPEC, "org-1", "creator-1")
    assert wid
    wf = orch._workflows[wid]
    assert wf.current_state.value == "requirements_validated"

    orch.advance_pipeline(wid)
    # Gate remains pending: no advance past the requirements gate.
    assert wf.current_state.value == "requirements_validated"


def test_gate_approval_advances_pipeline(orch):
    wid = orch.start_pipeline(YAML_SPEC, "org-1", "creator-1")
    wf = orch._workflows[wid]

    # Find the requirements gate
    gate = next(g for g in wf.gates if "requirements" in g.name.lower())
    assert gate.decision_id is None

    approved = orch.approve_gate(wid, gate.id, "approver-1")
    assert approved
    assert gate.decision_id is not None
    # Pipeline should now advance to the first task state.
    orch.advance_pipeline(wid)
    assert wf.current_state != "requirements_validated"


def test_task_completion_advances_to_next_state(orch):
    wid = orch.start_pipeline(YAML_SPEC, "org-1", "creator-1")
    wf = orch._workflows[wid]

    gate = next(g for g in wf.gates if "requirements" in g.name.lower())
    orch.approve_gate(wid, gate.id, "approver-1")
    orch.advance_pipeline(wid)

    tasks = orch.list_tasks(wid)
    assert tasks, "expected a task to be created after gate approval"

    # Complete the architecture task
    task = tasks[0]
    task.result = {"architecture": {"name": "demo"}}
    orch.handle_task_completion(task)

    assert wf.current_state.value == "architecture_generated"


def test_canonical_factory_dispatches_pipeline_tasks():
    factory = DictTaskExecutorFactory(
        executors=build_pipeline_executor_registry(_FakeStructuredGenerator())
    )
    result = factory.get("generate_code").execute({"name": "demo"})
    assert result["status"] == "success"
    with pytest.raises(LookupError):
        factory.get("unknown_type")


def test_pipeline_state_survives_orchestrator_restart(tmp_path):
    store = PipelineStateStore(tmp_path / "pipeline.json")
    first = PipelineOrchestrator(_FakeRuntime(), state_store=store)
    wid = first.start_pipeline(YAML_SPEC, "org-1", "creator-1")
    gate = next(
        g for g in first._workflows[wid].gates if "requirements" in g.name.lower()
    )
    first.approve_gate(wid, gate.id, "approver-1")
    assert first.list_tasks(wid)

    restored = PipelineOrchestrator(_FakeRuntime(), state_store=store)
    assert restored.get_pipeline_status(wid)["state_name"] == "architecture_generating"
    assert len(restored.list_tasks(wid)) == 1
    restored_gate = next(g for g in restored._workflows[wid].gates if g.id == gate.id)
    assert restored_gate.decision_id == gate.decision_id
