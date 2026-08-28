import pytest
from unittest.mock import MagicMock
from domain.pipeline_states import PipelineState
from domain.workflow import Workflow, WorkflowStatus
from runtime.pipeline_orchestrator import PipelineOrchestrator

def test_transition_raises_when_runtime_fails():
    mock_runtime = MagicMock()
    mock_runtime.transition_workflow.side_effect = RuntimeError("DB connection lost")

    orchestrator = PipelineOrchestrator(runtime=mock_runtime)
    wf = Workflow(
        id="wf-1",
        name="test",
        status=WorkflowStatus.RUNNING,
    )
    initial_state = wf.current_state

    with pytest.raises(RuntimeError, match="DB connection lost"):
        orchestrator._transition(wf, PipelineState.REQUIREMENTS_VALIDATED)

    assert wf.current_state == initial_state
