# runtime/pipeline_orchestrator.py
"""Pipeline orchestrator for the DOR software factory.

Drives a workflow through the pipeline states by creating tasks for each
state, dispatching them through the canonical ``TaskExecutionService`` when
available, and advancing the workflow whenever gates/tasks complete.

Design note (2026-08): the canonical ``DORRuntime`` (runtime/core.py) exposes
``create_workflow(context, name, description)`` and
``transition_workflow(context, workflow_id, new_state, evidence)`` but no
task registry. The orchestrator therefore owns a small in-memory task
registry and adapts to whatever runtime it is handed:
  * if ``runtime.transition_workflow(context, workflow_id, new_state, evidence)``
    exists, it is used for state changes;
  * otherwise the workflow's ``current_state`` is advanced directly.
"""

import logging
from typing import Any, Dict, Optional

from domain.pipeline_states import PipelineState
from domain.pipeline_task_mapping import PipelineTaskMapping
from domain.task import Task, TaskStatus
from domain.workflow import Workflow, WorkflowState
from runtime.core import DORRuntime
from services.pipeline_adapter import PipelineAdapter

logger = logging.getLogger(__name__)

_TERMINAL = frozenset({
    PipelineState.RELEASED,
    PipelineState.FAILED,
    PipelineState.CANCELLED,
})


class PipelineOrchestrator:
    """Orchestrates the software factory pipeline."""

    def __init__(self, runtime: DORRuntime, adapter: Optional[PipelineAdapter] = None):
        self._runtime = runtime
        self._adapter = adapter or PipelineAdapter()
        # In-memory workflow/task registry (independent of DORRuntime).
        self._workflows: Dict[str, Workflow] = {}
        self._tasks: Dict[str, Task] = {}

    # ------------------------------------------------------------------ #
    # Registry helpers
    # ------------------------------------------------------------------ #
    def _get_workflow(self, workflow_id: str) -> Optional[Workflow]:
        wf = self._workflows.get(workflow_id)
        if wf is not None:
            return wf
        # Fall back to the runtime (core signature: get_workflow(context, id))
        getter = getattr(self._runtime, "get_workflow", None)
        if getter is None:
            return None
        try:
            return getter(None, workflow_id)  # context may be unknown here
        except TypeError:
            try:
                return getter(workflow_id)
            except Exception:
                return None

    def _transition(self, workflow: Workflow, new_state: PipelineState, evidence: Optional[dict] = None) -> None:
        """Advance a workflow state, preferring the canonical runtime signature."""
        transition = getattr(self._runtime, "transition_workflow", None)
        if transition is not None:
            try:
                transition(None, workflow.id, new_state, evidence)
                workflow.current_state = new_state
                return
            except TypeError:
                pass
            except Exception as exc:  # runtime may reject without context
                logger.warning("runtime transition failed (%s); advancing locally", exc)
        workflow.current_state = new_state

    # ------------------------------------------------------------------ #
    # Public API (synchronous, pipeline-level)
    # ------------------------------------------------------------------ #
    def start_pipeline(
        self,
        requirements_yaml: str,
        organization_id: str,
        created_by: str,
    ) -> str:
        """Create and start a pipeline from a requirements YAML document."""
        workflow = self._adapter.create_pipeline_from_yaml(
            yaml_content=requirements_yaml,
            organization_id=organization_id,
            created_by=created_by,
        )
        self._workflows[workflow.id] = workflow
        # Validate requirements => REQUIREMENTS_VALIDATED
        self._transition(workflow, PipelineState.REQUIREMENTS_VALIDATED, {"requirements_complete": True})
        logger.info("Pipeline %s started (state=%s)", workflow.id, workflow.current_state)
        return workflow.id

    def get_pipeline_status(self, workflow_id: str) -> Dict[str, Any]:
        workflow = self._get_workflow(workflow_id)
        if workflow is None:
            raise ValueError(f"Pipeline {workflow_id} not found")
        tasks = [
            {
                "id": t.id,
                "task_type": (t.metadata or {}).get("task_type", getattr(t, "task_type", None) or t.name),
                "status": getattr(t.status, "value", str(getattr(t, "status", "pending"))),
            }
            for t in self._tasks.values()
            if t.workflow_id == workflow_id
        ]
        return {
            "workflow_id": workflow_id,
            "current_state": workflow.current_state,
            "state_name": getattr(workflow.current_state, "value", str(workflow.current_state)),
            "tasks": tasks,
            "context": dict(workflow.context or {}),
        }

    def advance_pipeline(self, workflow_id: str) -> None:
        """Create the next task for the current state (stops at gates)."""
        workflow = self._get_workflow(workflow_id)
        if workflow is None:
            raise ValueError(f"Pipeline {workflow_id} not found")

        if workflow.current_state in _TERMINAL:
            return

        if self._has_pending_gate(workflow):
            logger.info("Pipeline %s waiting at gate in state %s", workflow_id, workflow.current_state)
            return

        # If the current state requires a task, create it.
        if PipelineTaskMapping.is_task_state(workflow.current_state):
            task_config = PipelineTaskMapping.get_task_config(workflow.current_state)
            existing = [
                t for t in self._tasks.values()
                if t.workflow_id == workflow_id
                and (t.metadata or {}).get("task_type") == task_config["task_type"]
            ]
            if existing:
                return
            task = Task(
                id=f"task-{workflow_id[:8]}-{task_config['task_type']}",
                name=task_config["task_type"],
                workflow_id=workflow_id,
                priority=1,
                metadata={
                    "task_type": task_config["task_type"],
                    "component": task_config.get("component", ""),
                },
                execution_parameters={
                    "workflow_id": workflow_id,
                    "current_state": workflow.current_state.value,
                    "context": dict(workflow.context or {}),
                },
            )
            task.status = TaskStatus.PENDING
            self._tasks[task.id] = task
            logger.info("Created task %s for pipeline %s", task.name, workflow_id)
            return

        # No task required: advance to the next non-gated state (gate logic inside).
        next_state = self._get_next_state_for_pipeline(workflow)
        if next_state is not None:
            self._transition(workflow, next_state, {"auto_advance": True})
            logger.info("Pipeline %s advanced to %s", workflow_id, next_state)
            self.advance_pipeline(workflow_id)  # continue until a task/gate/terminal

    def handle_task_completion(self, task: Task) -> None:
        """Handle a completed task: merge result, transition, continue."""
        task_type = (task.metadata or {}).get("task_type")
        if not task_type:
            task_type = getattr(task, "task_type", None) or task.name
        next_state = PipelineTaskMapping.get_next_state(task_type)
        if next_state is None:
            return
        workflow = self._get_workflow(task.workflow_id)
        if workflow is None:
            return

        if getattr(task, "result", None):
            workflow.context.update(task.result)

        # A completed task clears its pending gate (if any).
        task.status = TaskStatus.SUCCEEDED
        self._transition(workflow, next_state, {"task_completed": task_type})
        self._tasks[task.id] = task
        logger.info("Pipeline %s -> %s after task %s", workflow.id, next_state, task_type)

        # Advance further automatically.
        self.advance_pipeline(workflow.id)

    # ------------------------------------------------------------------ #
    # Internals
    # ------------------------------------------------------------------ #
    def _has_pending_gate(self, workflow: Workflow) -> bool:
        """True when the current state's transition requires an unapproved gate."""
        for transition in getattr(workflow, "transitions", []) or []:
            if not hasattr(transition, "from_state"):
                continue
            if transition.from_state != workflow.current_state:
                continue
            gate_id = getattr(transition, "gate_id", None)
            if not gate_id:
                continue
            gate = next((g for g in workflow.gates if g.id == gate_id), None)
            if gate is not None and not getattr(gate, "decision_id", None):
                return True
        return False

    def approve_gate(self, workflow_id: str, gate_id: str, approver: str, decision: str = "approved") -> bool:
        """Approve a pending gate and mark it resolved (decision_id set)."""
        workflow = self._get_workflow(workflow_id)
        if workflow is None:
            raise ValueError(f"Pipeline {workflow_id} not found")
        gate = next((g for g in workflow.gates if g.id == gate_id), None)
        if gate is None:
            raise ValueError(f"Gate {gate_id} not found")
        if gate.decision_id:
            raise ValueError(f"Gate {gate_id} already resolved")
        gate.decision_id = f"decision-{workflow_id[:8]}-{gate_id}"
        # Record approval in workflow context for auditability.
        workflow.context["gate_approvals"] = workflow.context.get("gate_approvals", []) + [
            {"gate_id": gate_id, "approver": approver, "decision": decision}
        ]
        self.advance_pipeline(workflow_id)
        return True

    def _get_next_state_for_pipeline(self, workflow: Workflow) -> Optional[PipelineState]:
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
        try:
            current_index = state_sequence.index(workflow.current_state)
        except ValueError:
            return None
        if current_index + 1 >= len(state_sequence):
            return None

        next_state = state_sequence[current_index + 1]
        # skip states that have gates (they need human approval via approve_gate).
        if self._has_pending_gate(workflow):
            return None
        return next_state

    def list_tasks(self, workflow_id: str) -> list[Task]:
        return [t for t in self._tasks.values() if t.workflow_id == workflow_id]
