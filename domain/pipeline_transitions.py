# domain/pipeline_transitions.py

from domain.workflow import Transition
from domain.pipeline_states import PipelineState

def get_pipeline_transitions() -> list[Transition]:
    """Get all transitions for the software factory pipeline"""
    
    return [
        # ===== Requirements phase =====
        Transition(
            from_state=PipelineState.REQUIREMENTS_DRAFT,
            to_state=PipelineState.REQUIREMENTS_VALIDATED,
            condition="requirements.complete == true",
            description="Validate that all requirements are complete"
        ),
        Transition(
            from_state=PipelineState.REQUIREMENTS_VALIDATED,
            to_state=PipelineState.REQUIREMENTS_APPROVED,
            gate_id="gate_requirements_approval",
            description="Human approves requirements specification"
        ),
        
        # ===== Architecture phase =====
        Transition(
            from_state=PipelineState.REQUIREMENTS_APPROVED,
            to_state=PipelineState.ARCHITECTURE_GENERATING,
            condition="architecture_generation_enabled == true",
            description="Start architecture generation"
        ),
        Transition(
            from_state=PipelineState.ARCHITECTURE_GENERATING,
            to_state=PipelineState.ARCHITECTURE_GENERATED,
            condition="architecture_generated == true",
            description="Architecture has been generated"
        ),
        Transition(
            from_state=PipelineState.ARCHITECTURE_GENERATED,
            to_state=PipelineState.ARCHITECTURE_APPROVED,
            gate_id="gate_architecture_approval",
            description="Human approves architecture"
        ),
        
        # ===== Contracts phase =====
        Transition(
            from_state=PipelineState.ARCHITECTURE_APPROVED,
            to_state=PipelineState.CONTRACTS_GENERATING,
            condition="contract_generation_enabled == true",
            description="Start contract generation"
        ),
        Transition(
            from_state=PipelineState.CONTRACTS_GENERATING,
            to_state=PipelineState.CONTRACTS_GENERATED,
            condition="contracts_generated == true",
            description="Contracts have been generated"
        ),
        Transition(
            from_state=PipelineState.CONTRACTS_GENERATED,
            to_state=PipelineState.CONTRACTS_APPROVED,
            gate_id="gate_contracts_approval",
            description="Human approves contracts"
        ),
        
        # ===== Code phase =====
        Transition(
            from_state=PipelineState.CONTRACTS_APPROVED,
            to_state=PipelineState.CODE_GENERATING,
            condition="code_generation_enabled == true",
            description="Start code generation"
        ),
        Transition(
            from_state=PipelineState.CODE_GENERATING,
            to_state=PipelineState.CODE_GENERATED,
            condition="code_generated == true",
            description="Code has been generated"
        ),
        
        # ===== Tests phase =====
        Transition(
            from_state=PipelineState.CODE_GENERATED,
            to_state=PipelineState.TESTS_GENERATING,
            condition="test_generation_enabled == true",
            description="Start test generation"
        ),
        Transition(
            from_state=PipelineState.TESTS_GENERATING,
            to_state=PipelineState.TESTS_GENERATED,
            condition="tests_generated == true",
            description="Tests have been generated"
        ),
        Transition(
            from_state=PipelineState.TESTS_GENERATED,
            to_state=PipelineState.TESTS_RUNNING,
            condition="test_execution_enabled == true",
            description="Start test execution"
        ),
        Transition(
            from_state=PipelineState.TESTS_RUNNING,
            to_state=PipelineState.TESTS_PASSED,
            condition="tests_passed == true",
            description="All tests passed"
        ),
        Transition(
            from_state=PipelineState.TESTS_RUNNING,
            to_state=PipelineState.TESTS_FAILED,
            condition="tests_failed == true",
            description="Tests failed"
        ),
        
        # ===== Deployment phase =====
        Transition(
            from_state=PipelineState.TESTS_PASSED,
            to_state=PipelineState.DEPLOYING,
            condition="deployment_enabled == true",
            description="Start deployment"
        ),
        Transition(
            from_state=PipelineState.DEPLOYING,
            to_state=PipelineState.DEPLOYED,
            condition="deployed == true",
            description="Deployment complete"
        ),
        Transition(
            from_state=PipelineState.DEPLOYED,
            to_state=PipelineState.RELEASE_APPROVED,
            gate_id="gate_release_approval",
            description="Human approves release"
        ),
        Transition(
            from_state=PipelineState.RELEASE_APPROVED,
            to_state=PipelineState.RELEASED,
            condition="release_complete == true",
            description="Release complete"
        ),
        
        # ===== Failure transitions =====
        Transition(
            from_state=PipelineState.TESTS_FAILED,
            to_state=PipelineState.FAILED,
            condition="error != null",
            description="Tests failed → pipeline fails"
        ),
        Transition(
            from_state=PipelineState.FAILED,
            to_state=PipelineState.CANCELLED,
            condition="cancelled == true",
            description="Pipeline cancelled"
        ),
    ]
