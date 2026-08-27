# runtime/pipeline_orchestrator.py

from typing import Optional, Dict, Any, List
import logging
import os
import uuid
from datetime import datetime, timezone

from domain.pipeline_states import PipelineState
from domain.pipeline_transitions import get_pipeline_transitions
from services.pipeline_adapter import PipelineAdapter
from runtime.core import DORRuntime

logger = logging.getLogger(__name__)

#: Gate approval ids from the pipeline state machine
GATE_IDS = {
    "gate_requirements_approval",
    "gate_architecture_approval",
    "gate_contracts_approval",
    "gate_release_approval",
}


class PipelineOrchestrator:
    """
    Orchestrates the software factory pipeline from requirements to release.

    Pipelines are keyed by a pipeline id (workflow_id) and tracked in-memory
    for the process lifetime, with the source of truth being the PipelineState
    state machine defined in domain.pipeline_transitions.
    """

    def __init__(self, runtime: DORRuntime):
        self._runtime = runtime
        self._pipelines: Dict[str, Dict[str, Any]] = {}

    # ---------------------------------------------------------------- helpers
    def _load(self, workflow_id: str) -> Dict[str, Any]:
        pipeline = self._pipelines.get(workflow_id)
        if not pipeline:
            raise KeyError(f"Pipeline {workflow_id} not found")
        return pipeline

    def _persist(self, workflow_id: str, pipeline: Dict[str, Any]) -> None:
        pipeline["updated_at"] = datetime.now(timezone.utc).isoformat()
        self._pipelines[workflow_id] = pipeline

    def _snapshot(self, workflow_id: str) -> Dict[str, Any]:
        p = self._load(workflow_id)
        return {
            "workflow_id": workflow_id,
            "current_state": p["state"].value,
            "project_name": p.get("project_name"),
            "version": p.get("version"),
            "pending_gate": p.get("pending_gate"),
            "approved_gates": list(p.get("approved_gates", [])),
            "created_at": p.get("created_at"),
            "updated_at": p.get("updated_at"),
            "error": p.get("error"),
            "tasks": list(p.get("tasks", [])),
        }

    # -------------------------------------------------------------- lifecycle
    async def start_pipeline(
        self, requirements_yaml: str, organization_id: str, created_by: str
    ) -> str:
        workflow_id = str(uuid.uuid4())

        # Parse and validate the YAML spec via the adapter's validation logic
        adapter = PipelineAdapter(None)
        spec = adapter.parse_spec(requirements_yaml)

        pipeline = {
            "id": workflow_id,
            "organization_id": organization_id,
            "created_by": created_by,
            "state": PipelineState.REQUIREMENTS_DRAFT,
            "project_name": spec.get("project_name"),
            "project_description": spec.get("project_description"),
            "version": spec.get("version"),
            "requirements": spec.get("requirements", []),
            "approved_gates": [],
            "pending_gate": None,
            "error": None,
            "tasks": [],
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        self._persist(workflow_id, pipeline)
        logger.info(f"Started pipeline {workflow_id} for {pipeline['project_name']}")
        return workflow_id

    async def get_pipeline_status(self, workflow_id: str) -> Dict[str, Any]:
        try:
            return self._snapshot(workflow_id)
        except KeyError as exc:
            raise ValueError(str(exc))

    async def decide_gate(
        self, workflow_id: str, gate_id: str, decision: str
    ) -> Dict[str, Any]:
        """Record a human gate decision (approved / rejected)."""
        if gate_id not in GATE_IDS:
            raise ValueError(f"Unknown gate: {gate_id}")

        pipeline = self._load(workflow_id)
        state = pipeline["state"]

        # Only the gate that the pipeline is currently waiting on can be decided.
        expected_gate = self._gate_for_state(state)
        if expected_gate is None:
            raise ValueError(
                f"Pipeline is in state '{state.value}'; no gate is pending."
            )
        if expected_gate != gate_id:
            raise ValueError(
                f"Pipeline is waiting on gate '{expected_gate}', not '{gate_id}'."
            )

        normalized = decision.strip().lower()
        if normalized not in ("approved", "reject", "rejected"):
            raise ValueError("decision must be 'approved' or 'rejected'")

        if normalized == "approved":
            approved = set(pipeline["approved_gates"])
            approved.add(gate_id)
            pipeline["approved_gates"] = sorted(approved)
            pipeline["pending_gate"] = None
            # Advance to the post-approval state, e.g.
            # REQUIREMENTS_VALIDATED -> REQUIREMENTS_APPROVED
            pipeline["state"] = self._next_after_approval(state)
            message = f"Gate '{gate_id}' approved"
        else:
            pipeline["state"] = PipelineState.FAILED
            pipeline["error"] = f"Gate {gate_id} rejected"
            message = f"Gate '{gate_id}' rejected - pipeline failed"

        self._persist(workflow_id, pipeline)
        return {
            "workflow_id": workflow_id,
            "status": "ok",
            "message": message,
            "current_state": pipeline["state"].value,
        }

    async def advance_pipeline(self, workflow_id: str) -> Dict[str, Any]:
        """Advance pipeline automatically as far as possible (past non-gate steps)."""
        pipeline = self._load(workflow_id)
        if pipeline["state"] in (PipelineState.FAILED, PipelineState.CANCELLED):
            raise ValueError(
                f"Pipeline is in terminal state '{pipeline['state'].value}'"
            )

        # If waiting on a gate, advancement is blocked until it is decided.
        pending = self._gate_for_state(pipeline["state"])
        if pending is not None:
            pipeline["pending_gate"] = pending
            self._persist(workflow_id, pipeline)
            raise ValueError(
                f"Pipeline is waiting on gate '{pending}' - approve it first"
            )

        # Apply auto-transitions (condition-driven steps).
        moved = False
        while True:
            nxt = self._auto_next(pipeline["state"])
            if nxt is None:
                break
            pipeline["state"] = nxt
            moved = True

        self._persist(workflow_id, pipeline)
        if moved:
            return {
                "workflow_id": workflow_id,
                "status": "ok",
                "message": f"Pipeline advanced to {pipeline['state'].value}",
                "current_state": pipeline["state"].value,
            }
        return {
            "workflow_id": workflow_id,
            "status": "ok",
            "message": f"Pipeline is at {pipeline['state'].value}",
            "current_state": pipeline["state"].value,
        }

    def list_pipelines(self, state: Optional[str] = None) -> List[Dict[str, Any]]:
        """Return a snapshot of all known pipelines (optionally filtered by state)."""
        out = []
        for wid in sorted(self._pipelines.keys()):
            snap = self._snapshot(wid)
            if state is not None and snap["current_state"] != state:
                continue
            out.append(snap)
        return out

    # ----------------------------------------------------------- state machine
    def _gate_for_state(self, state: PipelineState) -> Optional[str]:
        # Map each pre-approval state to the gate that unblocks the next state.
        mapping = {
            PipelineState.REQUIREMENTS_VALIDATED: "gate_requirements_approval",
            PipelineState.ARCHITECTURE_GENERATED: "gate_architecture_approval",
            PipelineState.CONTRACTS_GENERATED: "gate_contracts_approval",
            PipelineState.DEPLOYED: "gate_release_approval",
        }
        return mapping.get(state)

    def _next_after_approval(self, state: PipelineState) -> PipelineState:
        mapping = {
            PipelineState.REQUIREMENTS_VALIDATED: PipelineState.REQUIREMENTS_APPROVED,
            PipelineState.ARCHITECTURE_GENERATED: PipelineState.ARCHITECTURE_APPROVED,
            PipelineState.CONTRACTS_GENERATED: PipelineState.CONTRACTS_APPROVED,
            PipelineState.DEPLOYED: PipelineState.RELEASE_APPROVED,
        }
        return mapping.get(
            state,
            state,
        )

    def _auto_next(self, state: PipelineState) -> Optional[PipelineState]:
        """Return the next automatic (non-gate, non-approval) transition, or None."""
        # These transitions are condition-driven and treated as automatic steps
        # in this pipeline runner.
        automatic = {
            PipelineState.REQUIREMENTS_DRAFT: PipelineState.REQUIREMENTS_VALIDATED,
            PipelineState.REQUIREMENTS_APPROVED: PipelineState.ARCHITECTURE_GENERATING,
            PipelineState.ARCHITECTURE_GENERATING: PipelineState.ARCHITECTURE_GENERATED,
            PipelineState.ARCHITECTURE_APPROVED: PipelineState.CONTRACTS_GENERATING,
            PipelineState.CONTRACTS_GENERATING: PipelineState.CONTRACTS_GENERATED,
            PipelineState.CONTRACTS_APPROVED: PipelineState.CODE_GENERATING,
            PipelineState.CODE_GENERATING: PipelineState.CODE_GENERATED,
            PipelineState.CODE_GENERATED: PipelineState.TESTS_GENERATING,
            PipelineState.TESTS_GENERATING: PipelineState.TESTS_GENERATED,
            PipelineState.TESTS_GENERATED: PipelineState.TESTS_RUNNING,
            PipelineState.TESTS_RUNNING: PipelineState.TESTS_PASSED,
            PipelineState.TESTS_PASSED: PipelineState.DEPLOYING,
            PipelineState.DEPLOYING: PipelineState.DEPLOYED,
            PipelineState.RELEASE_APPROVED: PipelineState.RELEASED,
        }
        nxt = automatic.get(state)
        return nxt


# ---------------------------------------------------------------------------
# Singleton orchestrator accessor.
# The in-memory pipeline registry must be shared across all API requests, so
# all endpoints resolve the same process-level orchestrator instance.
# ---------------------------------------------------------------------------
from functools import lru_cache

@lru_cache(maxsize=1)
def get_pipeline_orchestrator() -> PipelineOrchestrator:
    runtime = DORRuntime(os.getenv("DATABASE_URL", "sqlite:///./dor_runtime.db"))
    return PipelineOrchestrator(runtime)
