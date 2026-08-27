# runtime/pipeline_orchestrator.py

from typing import Optional, Dict, Any
import logging

from domain.workflow import Workflow, WorkflowState
from domain.task import Task
from domain.pipeline_states import PipelineState
from domain.pipeline_task_mapping import PipelineTaskMapping
from runtime.core import DORRuntime

logger = logging.getLogger(__name__)

class PipelineOrchestrator:
    """
    Extends DORRuntime with pipeline-specific logic.
    Orchestrates the software factory pipeline from requirements to release.
    """
    
    def __init__(self, runtime: DORRuntime):
        self._runtime = runtime
        self._adapter = runtime.pipeline_adapter
    
    async def start_pipeline(self, requirements_yaml: str, organization_id: str, created_by: str) -> str:
        """
        Start a new software factory pipeline.
        
        Args:
            requirements_yaml: YAML requirements specification
            organization_id: Organization ID
            created_by: User ID who created the pipeline
            
        Returns:
            workflow_id: ID of the created pipeline workflow
        """
        # 1. Create workflow via adapter
        workflow = await self._adapter.create_pipeline_from_yaml(
            yaml_content=requirements_yaml,
            organization_id=organization_id,
            created_by=created_by,
        )
        
        # 2. Start the pipeline (validate requirements)
        workflow = await self._runtime.transition_workflow(
            workflow_id=workflow.id,
            to_state=PipelineState.REQUIREMENTS_VALIDATED,
            context={"requirements_complete": True},
        )
        
        logger.info(f"Pipeline {workflow.id} started in state {workflow.current_state}")
        return workflow.id
    
    async def get_pipeline_status(self, workflow_id: str) -> Dict[str, Any]:
        """Get the current status of a pipeline"""
        workflow = await self._runtime.get_workflow(workflow_id)
        if not workflow:
            raise ValueError(f"Pipeline {workflow_id} not found")
        
        # Get tasks for this workflow
        tasks = await self._runtime.list_tasks_by_workflow(workflow_id)
        
        return {
            "workflow_id": workflow.id,
            "current_state": workflow.current_state.value,
            "project_name": workflow.context.get("project_name"),
            "created_at": workflow.created_at.isoformat(),
            "updated_at": workflow.updated_at.isoformat(),
            "tasks": [
                {
                    "id": t.id,
                    "type": t.task_type,
                    "status": t.status.value,
                    "created_at": t.created_at.isoformat(),
                    "completed_at": t.completed_at.isoformat() if t.completed_at else None,
                }
                for t in tasks
            ],
            "error": workflow.context.get("error"),
        }
    
    async def advance_pipeline(self, workflow_id: str) -> None:
        """
        Advance the pipeline to the next state.
        Called after a task completes or a gate is approved.
        """
        workflow = await self._runtime.get_workflow(workflow_id)
        if not workflow:
            raise ValueError(f"Pipeline {workflow_id} not found")
        
        current_state = workflow.current_state
        
        # If terminal, do nothing
        if current_state in [PipelineState.RELEASED, PipelineState.FAILED, PipelineState.CANCELLED]:
            return
        
        # Find next task for current state
        if PipelineTaskMapping.is_task_state(current_state):
            # A task is required for this state
            task_config = PipelineTaskMapping.get_task_config(current_state)
            if task_config:
                # Check if task already exists
                existing_tasks = await self._runtime.list_tasks_by_workflow(
                    workflow_id,
                    task_type=task_config["task_type"],
                )
                if not existing_tasks:
                    # Create the task
                    await self._runtime.create_task(
                        workflow_id=workflow_id,
                        task_type=task_config["task_type"],
                        data={
                            "workflow_id": workflow_id,
                            "current_state": current_state.value,
                            "context": workflow.context,
                            "component": task_config["component"],
                        },
                        priority=1,
                    )
                    logger.info(f"Created task {task_config['task_type']} for workflow {workflow_id}")
        else:
            # No task required - transition to next state if possible
            # Check if there's a pending gate
            if self._has_pending_gate(workflow):
                logger.info(f"Pipeline {workflow_id} waiting for gate approval")
                return
            
            # Find the next state
            next_state = self._get_next_state_for_pipeline(workflow)
            if next_state:
                await self._runtime.transition_workflow(
                    workflow_id=workflow_id,
                    to_state=next_state,
                    context=workflow.context,
                )
                logger.info(f"Pipeline {workflow_id} advanced to {next_state}")
    
    def _has_pending_gate(self, workflow: Workflow) -> bool:
        """Check if there's a pending gate that needs approval"""
        for transition in workflow.transitions:
            if transition.from_state == workflow.current_state:
                if transition.gate_id:
                    # Check if gate is pending
                    gate = next((g for g in workflow.gates if g.id == transition.gate_id), None)
                    if gate and gate.decision_id:
                        return True
        return False
    
    def _get_next_state_for_pipeline(self, workflow: Workflow) -> Optional[PipelineState]:
        """Determine the next state based on the current state"""
        state_sequence = [
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
        
        current_index = -1
        for i, state in enumerate(state_sequence):
            if state == workflow.current_state:
                current_index = i
                break
        
        if current_index >= 0 and current_index + 1 < len(state_sequence):
            next_state = state_sequence[current_index + 1]
            # Check if transition is allowed
            transition = workflow.get_transition(workflow.current_state, next_state)
            if transition:
                # Check if we can transition
                can_transition = workflow.can_transition(
                    workflow.current_state,
                    next_state,
                    workflow.context,
                )
                if can_transition:
                    return next_state
        
        return None
    
    async def handle_task_completion(self, task: Task) -> None:
        """
        Handle task completion and advance the pipeline.
        Called from DORRuntime._on_task_completed()
        """
        # Get the next state for this task type
        next_state = PipelineTaskMapping.get_next_state(task.task_type)
        if not next_state:
            return
        
        # Transition the workflow
        workflow = await self._runtime.get_workflow(task.workflow_id)
        if not workflow:
            return
        
        # Update context with task result
        if task.result:
            workflow.context.update(task.result)
        
        # Transition to next state
        await self._runtime.transition_workflow(
            workflow_id=workflow.id,
            to_state=next_state,
            context=workflow.context,
        )
        
        # Advance to next task if needed
        await self.advance_pipeline(workflow.id)
