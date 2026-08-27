# domain/pipeline_task_mapping.py

from typing import Optional
from domain.pipeline_states import PipelineState

class PipelineTaskMapping:
    """Maps workflow states to task types"""
    
    STATE_TO_TASK = {
        PipelineState.ARCHITECTURE_GENERATING: {
            "task_type": "generate_architecture",
            "component": "phase4/council",
            "description": "Generate architecture using AI-6 Council",
        },
        PipelineState.CONTRACTS_GENERATING: {
            "task_type": "generate_contracts",
            "component": "generation",
            "description": "Generate OpenAPI/AsyncAPI contracts",
        },
        PipelineState.CODE_GENERATING: {
            "task_type": "generate_code",
            "component": "phase4/implementation_agent",
            "description": "Generate code from contracts",
        },
        PipelineState.TESTS_GENERATING: {
            "task_type": "generate_tests",
            "component": "phase4/verification",
            "description": "Generate tests from requirements and contracts",
        },
        PipelineState.TESTS_RUNNING: {
            "task_type": "run_tests",
            "component": "phase6",
            "description": "Execute tests in sandbox",
        },
        PipelineState.DEPLOYING: {
            "task_type": "deploy",
            "component": "services/docker",
            "description": "Deploy to target environment",
        },
        PipelineState.RELEASE_APPROVED: {
            "task_type": "release",
            "component": "services/release",
            "description": "Finalize release",
        },
    }
    
    @classmethod
    def get_task_config(cls, state: PipelineState) -> Optional[dict]:
        """Get task configuration for a state"""
        return cls.STATE_TO_TASK.get(state)
    
    @classmethod
    def is_task_state(cls, state: PipelineState) -> bool:
        """Check if a state requires a task to execute"""
        return state in cls.STATE_TO_TASK
    
    @classmethod
    def get_next_state(cls, task_type: str) -> Optional[PipelineState]:
        """Get the next pipeline state after a task completes"""
        reverse_map = {
            "generate_architecture": PipelineState.ARCHITECTURE_GENERATED,
            "generate_contracts": PipelineState.CONTRACTS_GENERATED,
            "generate_code": PipelineState.CODE_GENERATED,
            "generate_tests": PipelineState.TESTS_GENERATED,
            "run_tests": PipelineState.TESTS_PASSED,
            "deploy": PipelineState.DEPLOYED,
            "release": PipelineState.RELEASED,
        }
        return reverse_map.get(task_type)
