import pytest
import yaml
from domain.pipeline_states import PipelineState
from domain.pipeline_transitions import get_pipeline_transitions
from domain.pipeline_gates import get_pipeline_gates
from domain.pipeline_task_mapping import PipelineTaskMapping

def test_pipeline_states():
    assert PipelineState.REQUIREMENTS_DRAFT == "requirements_draft"
    assert PipelineState.RELEASED == "released"

def test_pipeline_transitions():
    transitions = get_pipeline_transitions()
    assert len(transitions) > 0

def test_pipeline_gates():
    gates = get_pipeline_gates()
    assert len(gates) == 4
    assert gates[0].id == "gate_requirements_approval"

def test_task_mapping():
    config = PipelineTaskMapping.get_task_config(PipelineState.ARCHITECTURE_GENERATING)
    assert config["task_type"] == "generate_architecture"
    assert PipelineTaskMapping.get_next_state("generate_architecture") == PipelineState.ARCHITECTURE_GENERATED
