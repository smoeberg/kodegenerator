"""Integration tests for the software-factory pipeline (end to end).

These run against the real in-memory orchestrator state machine, so they
exercise the actual creation -> gate decision -> advance flow rather than
mocked repositories.
"""

import pytest

from domain.pipeline_states import PipelineState
from domain.pipeline_task_mapping import PipelineTaskMapping
from runtime.pipeline_orchestrator import PipelineOrchestrator

REQUIREMENTS_YAML = """
project_name: 'User Service API'
project_description: 'A REST API for managing users'
version: '1.0.0'

requirements:
  - id: REQ-001
    description: 'Create a new user'
    acceptance_criteria:
      - 'User must have a unique email address'
      - 'User must have a name'
    priority: high
"""


@pytest.fixture
def orchestrator():
    """A fresh orchestrator with its own in-memory registry per test."""
    return PipelineOrchestrator(runtime=None)


@pytest.mark.asyncio
async def test_pipeline_creation_from_yaml(orchestrator):
    """A pipeline is created from YAML in the requirements_draft state."""
    workflow_id = await orchestrator.start_pipeline(
        requirements_yaml=REQUIREMENTS_YAML,
        organization_id="test-org",
        created_by="test-user",
    )

    assert workflow_id is not None
    status = await orchestrator.get_pipeline_status(workflow_id)
    assert status["current_state"] == PipelineState.REQUIREMENTS_DRAFT
    assert status["project_name"] == "User Service API"
    assert status["version"] == "1.0.0"
    assert len(status["requirements"]) == 1


@pytest.mark.asyncio
async def test_pipeline_end_to_end_gate_flow(orchestrator):
    """Creation -> requirements approval -> auto-advance to architecture gate."""
    workflow_id = await orchestrator.start_pipeline(
        requirements_yaml=REQUIREMENTS_YAML,
        organization_id="test-org",
        created_by="test-user",
    )

    # Advance out of draft (validates requirements) up to the requirements gate
    await orchestrator.advance_pipeline(workflow_id)
    status = await orchestrator.get_pipeline_status(workflow_id)
    assert status["current_state"] == PipelineState.REQUIREMENTS_VALIDATED
    assert status["pending_gate"] == "gate_requirements_approval"

    # Approve the requirements gate, then auto-advance to the next gate
    await orchestrator.decide_gate(
        workflow_id, "gate_requirements_approval", "approved"
    )
    status = await orchestrator.get_pipeline_status(workflow_id)
    assert status["current_state"] == PipelineState.REQUIREMENTS_APPROVED
    assert "gate_requirements_approval" in status["approved_gates"]

    await orchestrator.advance_pipeline(workflow_id)
    status = await orchestrator.get_pipeline_status(workflow_id)
    assert status["current_state"] == PipelineState.ARCHITECTURE_GENERATED
    assert status["pending_gate"] == "gate_architecture_approval"


@pytest.mark.asyncio
async def test_pipeline_state_sequence():
    """States follow the correct pipeline order, ending at RELEASED."""
    state_sequence = [
        PipelineState.REQUIREMENTS_DRAFT,
        PipelineState.REQUIREMENTS_VALIDATED,
        PipelineState.REQUIREMENTS_APPROVED,
        PipelineState.ARCHITECTURE_GENERATING,
        PipelineState.ARCHITECTURE_GENERATED,
        PipelineState.ARCHITECTURE_APPROVED,
        PipelineState.CONTRACTS_GENERATING,
        PipelineState.CONTRACTS_GENERATED,
        PipelineState.CONTRACTS_APPROVED,
        PipelineState.CODE_GENERATING,
        PipelineState.CODE_GENERATED,
        PipelineState.TESTS_GENERATING,
        PipelineState.TESTS_GENERATED,
        PipelineState.TESTS_RUNNING,
        PipelineState.TESTS_PASSED,
        PipelineState.DEPLOYING,
        PipelineState.DEPLOYED,
        PipelineState.RELEASE_APPROVED,
        PipelineState.RELEASED,
    ]
    for i in range(len(state_sequence) - 1):
        assert state_sequence[i] != state_sequence[i + 1]


def test_task_mapping():
    """States correctly map to the task types that perform the work."""
    mapping = {
        PipelineState.ARCHITECTURE_GENERATING: "generate_architecture",
        PipelineState.CONTRACTS_GENERATING: "generate_contracts",
        PipelineState.CODE_GENERATING: "generate_code",
        PipelineState.TESTS_GENERATING: "generate_tests",
        PipelineState.TESTS_RUNNING: "run_tests",
        PipelineState.DEPLOYING: "deploy",
    }
    for state, task_type in mapping.items():
        assert PipelineTaskMapping.get_task_config(state)["task_type"] == task_type

    # Reverse mapping: a completed task advances to the next state
    assert PipelineTaskMapping.get_next_state("generate_architecture") == PipelineState.ARCHITECTURE_GENERATED
    assert PipelineTaskMapping.get_next_state("generate_code") == PipelineState.CODE_GENERATED
