"""
Swarm Orchestrator Service.

Coordinates the end-to-end execution of a software generation project across:
1. Requirements Intake & Validation
2. Architecture Synthesis & Contract Generation
3. WBS DAG Task Decomposition
4. Swarm Task Queue Management & Parallel Worker Dispatching
5. Gatekeeper Merge Verification & main integration
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from domain.requirements import RequirementsSpecification
from domain.architecture_contract_v1 import ArchitectureContractV1
from services.architecture_synthesis import ArchitectureSynthesisEngine, ArchitectureSynthesisResult
from services.wbs_orchestrator import WBSOrchestratorService, WBSTask
from services.swarm_task_queue import SwarmTaskQueue, QueuedTask, QueuedTaskStatus
from services.gatekeeper_daemon import GatekeeperDaemon

logger = logging.getLogger(__name__)


class SwarmProjectStatus(str, Enum):
    INITIALIZING = "INITIALIZING"
    SYNTHESIZING_ARCHITECTURE = "SYNTHESIZING_ARCHITECTURE"
    DECISION_REQUIRED = "DECISION_REQUIRED"
    BUILDING_WBS = "BUILDING_WBS"
    DISPATCHING_TASKS = "DISPATCHING_TASKS"
    PAUSED = "PAUSED"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


@dataclass(frozen=True)
class SwarmRunReport:
    """Immutable audit report of an end-to-end swarm execution run."""
    run_id: str
    project_id: str
    status: SwarmProjectStatus
    started_at: datetime
    finished_at: Optional[datetime]
    total_tasks: int
    completed_tasks: int
    failed_tasks: int
    architecture_contract: Optional[ArchitectureContractV1] = None
    wbs_tasks: Tuple[str, ...] = ()
    errors: Tuple[str, ...] = ()
    gatekeeper_results: Tuple[str, ...] = ()

    @property
    def progress_percent(self) -> float:
        if self.total_tasks == 0:
            return 100.0 if self.status == SwarmProjectStatus.COMPLETED else 0.0
        return round((self.completed_tasks / self.total_tasks) * 100.0, 2)


class SwarmOrchestrator:
    """
    Central governor orchestrating multi-agent code generation, WBS scheduling,
    fail-closed AST / sandbox validation, and gatekeeper integration.
    """

    def __init__(
        self,
        repo_root: Optional[Path] = None,
        signing_key: Optional[bytes] = None,
        task_queue: Optional[SwarmTaskQueue] = None,
        arch_engine: Optional[ArchitectureSynthesisEngine] = None,
        wbs_service: Optional[WBSOrchestratorService] = None,
        gatekeeper: Optional[GatekeeperDaemon] = None,
    ) -> None:
        self.repo_root = repo_root or Path.cwd()
        self.signing_key = signing_key or b"swarm-orchestrator-authority-key-32b"
        self.task_queue = task_queue or SwarmTaskQueue()
        self.arch_engine = arch_engine or ArchitectureSynthesisEngine()
        self.wbs_service = wbs_service or WBSOrchestratorService()
        self._gatekeeper = gatekeeper

        self._projects: Dict[str, Dict[str, Any]] = {}
        self._is_paused = False

    @property
    def gatekeeper(self) -> GatekeeperDaemon:
        if self._gatekeeper is None:
            self._gatekeeper = GatekeeperDaemon(
                repository_root=self.repo_root,
                signing_key=self.signing_key,
            )
        return self._gatekeeper

    def start_project(
        self,
        requirements: RequirementsSpecification,
        project_id: Optional[str] = None,
    ) -> SwarmRunReport:
        """
        Start end-to-end swarm synthesis from requirements to executable WBS.
        """
        pid = project_id or f"proj-{uuid.uuid4().hex[:8]}"
        run_id = f"run-{uuid.uuid4().hex[:8]}"
        started_at = datetime.now(timezone.utc)

        # 1. Synthesize Architecture
        arch_res = self.arch_engine.synthesize(requirements)

        if arch_res.decisions:
            self._projects[pid] = {
                "run_id": run_id,
                "status": SwarmProjectStatus.DECISION_REQUIRED,
                "started_at": started_at,
                "arch_result": arch_res,
                "requirements": requirements,
                "completed_tasks": 0,
                "total_tasks": 0,
                "failed_tasks": 0,
                "errors": ("Architecture requires controller decision or approval",),
            }
            return SwarmRunReport(
                run_id=run_id,
                project_id=pid,
                status=SwarmProjectStatus.DECISION_REQUIRED,
                started_at=started_at,
                finished_at=None,
                total_tasks=0,
                completed_tasks=0,
                failed_tasks=0,
                errors=("Architecture requires controller decision or approval",),
            )

        contract = arch_res.contract

        # 2. Decompose into WBS Tasks
        tasks_list, _ = self.wbs_service.generate_from_contract(contract, workflow_id=pid)

        # 3. Populate Swarm Task Queue
        total_tasks = self.task_queue.enqueue_wbs_plan(tasks_list)
        task_names = [t.task.name for t in tasks_list]

        self._projects[pid] = {
            "run_id": run_id,
            "status": SwarmProjectStatus.DISPATCHING_TASKS,
            "started_at": started_at,
            "contract": contract,
            "wbs_task_names": tuple(task_names),
            "total_tasks": total_tasks,
            "completed_tasks": 0,
            "failed_tasks": 0,
            "gatekeeper_results": [],
            "errors": [],
        }

        return self.get_project_status(pid)

    def dispatch_worker_cycle(self, worker_id: str, capabilities: Optional[List[str]] = None) -> Optional[QueuedTask]:
        """
        Worker calls this to claim and execute the next eligible task from the queue.
        """
        if self._is_paused:
            return None

        caps = capabilities or [
            "cap.domain.modeling", "cap.architecture.design", "cap.code.generation",
            "cap.contract.design", "cap.implementation", "cap.ast.write",
            "cap.run.tests", "cap.verification", "cap.sandbox.testing",
            "cap.security.audit", "cap.penetration.test", "cap.code.review",
            "cap.documentation"
        ]
        return self.task_queue.claim_next_task(agent_id=worker_id, capabilities=caps)

    def complete_worker_task(
        self,
        task_id: str,
        worker_id: str,
        success: bool,
        patch_result: Optional[Any] = None,
        error_message: Optional[str] = None,
    ) -> bool:
        """
        Records completion or failure of a worker task and updates project progress.
        """
        try:
            if success:
                self.task_queue.complete_task(task_id=task_id, agent_id=worker_id, patch_result=patch_result or {})
            else:
                self.task_queue.fail_task(task_id=task_id, agent_id=worker_id, error=error_message or "Unknown failure")

            # Update matching project
            for p in self._projects.values():
                p_tasks = list(self.task_queue._tasks.values())
                p["completed_tasks"] = sum(t.status == QueuedTaskStatus.COMPLETED for t in p_tasks)
                p["failed_tasks"] = sum(t.status == QueuedTaskStatus.FAILED for t in p_tasks)
                pending = sum(t.status in (QueuedTaskStatus.PENDING, QueuedTaskStatus.CLAIMED) for t in p_tasks)
                if pending == 0:
                    p["status"] = SwarmProjectStatus.COMPLETED if p["failed_tasks"] == 0 else SwarmProjectStatus.FAILED
            return True
        except Exception as e:
            logger.error("Failed to complete worker task: %s", e)
            return False

    def pause(self) -> None:
        """Pause swarm task dispatching."""
        self._is_paused = True

    def resume(self) -> None:
        """Resume swarm task dispatching."""
        self._is_paused = False

    def get_project_status(self, project_id: str) -> SwarmRunReport:
        """Retrieve the immutable snapshot report for a project."""
        p = self._projects.get(project_id)
        if not p:
            raise KeyError(f"Project not found: {project_id}")

        p_tasks = list(self.task_queue._tasks.values())
        completed = sum(t.status == QueuedTaskStatus.COMPLETED for t in p_tasks)
        failed = sum(t.status == QueuedTaskStatus.FAILED for t in p_tasks)

        return SwarmRunReport(
            run_id=p["run_id"],
            project_id=project_id,
            status=p["status"],
            started_at=p["started_at"],
            finished_at=datetime.now(timezone.utc) if p["status"] in (SwarmProjectStatus.COMPLETED, SwarmProjectStatus.FAILED) else None,
            total_tasks=p.get("total_tasks", len(p_tasks)),
            completed_tasks=completed,
            failed_tasks=failed,
            architecture_contract=p.get("contract"),
            wbs_tasks=p.get("wbs_task_names", ()),
            errors=tuple(p.get("errors", [])),
            gatekeeper_results=tuple(p.get("gatekeeper_results", [])),
        )
