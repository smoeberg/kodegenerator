import pytest
from datetime import datetime, timezone
from pathlib import Path

from domain.requirements import (
    AcceptanceCriterion,
    Requirement,
    RequirementsSpecification,
    approval_for,
)
from services.swarm_orchestrator import (
    SwarmOrchestrator,
    SwarmProjectStatus,
    SwarmRunReport,
)
from services.swarm_task_queue import SwarmTaskQueue, QueuedTaskStatus


def make_valid_spec(name: str = "order-processor") -> RequirementsSpecification:
    draft = RequirementsSpecification(
        schema_version="1.0",
        specification_id=f"REQ-{name}",
        project={"name": name, "id": name},
        version="1.0.0",
        status="draft",
        intent={"goal": "Process orders through a secure API"},
        functional_requirements=(Requirement("FR-001", "Expose an API endpoint to create orders", "human"),),
        non_functional_requirements=(Requirement("NFR-001", "The API must be auditable", "human"),),
        data_requirements=(Requirement("DR-001", "Persist orders with transactional integrity", "human"),),
        integration_requirements=(Requirement("IR-001", "Integrate with a payment API", "human"),),
        constraints=(),
        acceptance_criteria=(AcceptanceCriterion("AC-001", "An order can be created", requirement_ids=("FR-001",)),),
    )
    app = approval_for(draft, "controller-smoeberg")
    return RequirementsSpecification(
        schema_version=draft.schema_version,
        specification_id=draft.specification_id,
        project=draft.project,
        version=draft.version,
        status="approved",
        intent=draft.intent,
        functional_requirements=draft.functional_requirements,
        non_functional_requirements=draft.non_functional_requirements,
        data_requirements=draft.data_requirements,
        integration_requirements=draft.integration_requirements,
        constraints=draft.constraints,
        acceptance_criteria=draft.acceptance_criteria,
        approval=app,
    )


class TestSwarmOrchestrator:
    def test_start_project_end_to_end(self, tmp_path):
        queue = SwarmTaskQueue()
        orch = SwarmOrchestrator(repo_root=tmp_path, task_queue=queue)
        spec = make_valid_spec("e2e-swarm-app")

        report = orch.start_project(spec, project_id="e2e-001")

        assert report.project_id == "e2e-001"
        assert report.status == SwarmProjectStatus.DISPATCHING_TASKS
        assert report.total_tasks > 0
        assert report.architecture_contract is not None
        assert report.completed_tasks == 0

        # Worker 1 claims task
        worker_task = orch.dispatch_worker_cycle(worker_id="worker-01")
        assert worker_task is not None
        assert worker_task.task_id is not None

        # Worker 1 completes task
        ok = orch.complete_worker_task(
            task_id=worker_task.task_id,
            worker_id="worker-01",
            success=True,
            patch_result={"artifact": "models.py", "lines": 42},
        )
        assert ok is True

        updated_report = orch.get_project_status("e2e-001")
        assert updated_report.completed_tasks == 1
        assert updated_report.progress_percent > 0.0

    def test_pause_and_resume_controls(self, tmp_path):
        queue = SwarmTaskQueue()
        orch = SwarmOrchestrator(repo_root=tmp_path, task_queue=queue)
        spec = make_valid_spec("pause-test-app")

        orch.start_project(spec, project_id="pause-001")
        orch.pause()

        # Cannot claim when paused
        claim_paused = orch.dispatch_worker_cycle(worker_id="worker-02")
        assert claim_paused is None

        # Resume allows claiming
        orch.resume()
        claim_resumed = orch.dispatch_worker_cycle(worker_id="worker-02")
        assert claim_resumed is not None
