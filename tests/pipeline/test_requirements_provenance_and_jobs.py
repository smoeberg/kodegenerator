"""Completion plan, step 1: requirements provenance and job records.

Every pipeline task carries the exact requirements revision it was built on,
every artifact records that revision, a result built on a superseded
revision is rejected, and every agent job gets a job record.
"""

from __future__ import annotations

import pytest

from domain.agent_job import (
    DOR_PIPELINE_EXECUTOR,
    MEASUREMENT_KEYS,
    AgentJobRecord,
    AgentJobRecordError,
    AgentJobStatus,
)
from domain.pipeline_states import PipelineState
from domain.requirements_provenance import (
    RequirementsProvenanceError,
    RequirementsRef,
    requirements_fingerprint,
)
from domain.task import TaskStatus
from runtime.pipeline_orchestrator import PipelineOrchestrator
from runtime.pipeline_registry import PipelineAwareQueue
from services.swarm_task_queue import SwarmTaskQueue

YAML_SPEC = """
project_name: Demo
project_description: A demo pipeline
version: "1.0"
requirements:
  - id: R1
    description: User can log in
    acceptance_criteria: ["GET /health returns 200"]
  - id: R2
    description: User can log out
    acceptance_criteria: ["POST /logout returns 204"]
"""

CHANGED_SPEC = YAML_SPEC.replace("User can log out", "User can log out everywhere")


class _Runtime:
    def get_workflow(self, *args):
        return None


class _MemoryStore:
    def __init__(self) -> None:
        self.snapshot = None

    def save(self, snapshot) -> None:
        self.snapshot = snapshot

    def load(self):
        return self.snapshot


def _orchestrator(**kwargs) -> PipelineOrchestrator:
    return PipelineOrchestrator(_Runtime(), **kwargs)


def _to_architecture_task(orch: PipelineOrchestrator):
    wid = orch.start_pipeline(YAML_SPEC, "org-1", "owner")
    workflow = orch._workflows[wid]
    gate = next(g for g in workflow.gates if "requirements" in g.name.lower())
    orch.approve_gate(wid, gate.id, "owner")
    orch.advance_pipeline(wid)
    (task,) = orch.list_tasks(wid)
    return wid, workflow, task


# --------------------------------------------------------------------- #
# Domain
# --------------------------------------------------------------------- #
def test_fingerprint_is_independent_of_key_order() -> None:
    assert requirements_fingerprint({"a": 1, "b": [1, 2]}) == requirements_fingerprint(
        {"b": [1, 2], "a": 1}
    )
    assert requirements_fingerprint({"a": 1}) != requirements_fingerprint({"a": 2})


def test_ref_derives_ids_and_rejects_duplicates() -> None:
    spec = {"version": "2", "requirements": [{"id": "R1"}, {"id": "R2"}]}
    ref = RequirementsRef.derive(spec, revision=1)
    assert ref.requirement_ids == ("R1", "R2")
    assert ref.declared_version == "2"
    assert RequirementsRef.from_dict(ref.to_dict()) == ref

    with pytest.raises(RequirementsProvenanceError):
        RequirementsRef.derive({"requirements": [{"id": "R1"}, {"id": "R1"}]}, 1)
    with pytest.raises(RequirementsProvenanceError):
        RequirementsRef.derive({"requirements": []}, 1)
    with pytest.raises(RequirementsProvenanceError):
        RequirementsRef.derive(spec, revision=0)


def test_job_record_closes_once_and_rejects_unknown_measurements() -> None:
    job = AgentJobRecord(
        job_id="job-1",
        organization_id="org-1",
        workflow_id="wf",
        task_id="t",
        task_type="generate_code",
        role="coder",
        attempt=1,
        requirements=None,
    )
    assert job.agent.tool == DOR_PIPELINE_EXECUTOR
    closed = job.start("worker-1").close(
        AgentJobStatus.SUCCEEDED, usage={"input_tokens": 10}
    )
    assert closed.agent.worker_id == "worker-1"
    assert closed.duration_seconds is not None and closed.duration_seconds >= 0
    assert closed.usage == {"input_tokens": 10}
    with pytest.raises(AgentJobRecordError):
        closed.close(AgentJobStatus.FAILED)
    with pytest.raises(AgentJobRecordError):
        job.record_measurements({"self_reported_quality": 1.0})
    measured = job.record_measurements({MEASUREMENT_KEYS[0]: 0})
    assert AgentJobRecord.from_dict(measured.to_dict()) == measured


# --------------------------------------------------------------------- #
# Orchestrator
# --------------------------------------------------------------------- #
def test_start_binds_revision_one_with_requirement_ids() -> None:
    orch = _orchestrator()
    wid = orch.start_pipeline(YAML_SPEC, "org-1", "owner")
    ref = orch.current_requirements_ref(orch._workflows[wid])
    assert ref is not None
    assert ref.revision == 1
    assert ref.requirement_ids == ("R1", "R2")
    assert ref.fingerprint == requirements_fingerprint(
        orch._workflows[wid].context["requirements"]
    )


def test_changed_requirements_become_new_revision_with_history() -> None:
    orch = _orchestrator()
    wid = orch.start_pipeline(YAML_SPEC, "org-1", "owner")
    workflow = orch._workflows[wid]
    first = orch.current_requirements_ref(workflow)

    orch.update_requirements(wid, YAML_SPEC)  # unchanged content
    assert orch.current_requirements_ref(workflow) == first

    orch.update_requirements(wid, CHANGED_SPEC)
    second = orch.current_requirements_ref(workflow)
    assert second.revision == 2
    assert second.fingerprint != first.fingerprint
    (superseded,) = workflow.context["requirements_history"]
    assert superseded["revision"] == 1
    assert superseded["fingerprint"] == first.fingerprint
    assert superseded["superseded_by"] == 2


def test_task_is_stamped_and_job_opened() -> None:
    orch = _orchestrator()
    wid, workflow, task = _to_architecture_task(orch)
    ref = orch.current_requirements_ref(workflow)
    assert task.metadata["requirements_ref"] == ref.to_dict()

    (job,) = orch.list_job_records(wid)
    assert job.task_id == task.id
    assert job.task_type == "generate_architecture"
    assert job.role == "architect"
    assert job.attempt == 1
    assert job.status == AgentJobStatus.QUEUED
    assert job.requirements == ref
    assert job.organization_id == "org-1"


def test_completion_records_artifact_provenance_and_closes_job() -> None:
    orch = _orchestrator()
    wid, workflow, task = _to_architecture_task(orch)
    task.result = {"architecture": {"name": "demo"}, "usage": {"input_tokens": 42}}
    orch.handle_task_completion(task)

    assert workflow.current_state == PipelineState.ARCHITECTURE_GENERATED
    provenance = workflow.context["artifact_provenance"]["generate_architecture"]
    assert provenance["task_id"] == task.id
    assert provenance["requirements_ref"]["revision"] == 1
    assert "architecture" in provenance["result_keys"]

    (job,) = orch.list_job_records(wid)
    assert job.status == AgentJobStatus.SUCCEEDED
    assert job.usage == {"input_tokens": 42}
    assert orch.get_pipeline_status(wid)["jobs"][0]["status"] == "succeeded"


def test_result_built_on_superseded_revision_is_rejected() -> None:
    import yaml

    orch = _orchestrator()
    wid, workflow, task = _to_architecture_task(orch)
    # The opdrag changes while the task is out (future change loop, step 9).
    orch._bind_requirements(workflow, yaml.safe_load(CHANGED_SPEC))

    task.result = {"architecture": {"name": "built on revision 1"}}
    orch.handle_task_completion(task)

    assert workflow.current_state == PipelineState.ARCHITECTURE_GENERATING
    assert "architecture" not in workflow.context
    assert task.status == TaskStatus.FAILED
    assert "stale requirements" in task.last_error
    (job,) = orch.list_job_records(wid)
    assert job.status == AgentJobStatus.REJECTED_STALE


def test_queue_claim_and_retry_produce_one_record_per_attempt() -> None:
    raw_queue = SwarmTaskQueue(lease_seconds=60)
    orch = _orchestrator(task_queue=raw_queue)
    wid, _, task = _to_architecture_task(orch)
    queue = PipelineAwareQueue(raw_queue, orch)

    claimed = queue.claim_next_task("worker-1", [])
    assert claimed.task_id == task.id
    (job,) = orch.list_job_records(wid)
    assert job.status == AgentJobStatus.RUNNING
    assert job.agent.worker_id == "worker-1"

    queue.fail_task(task.id, "worker-1", "transient", retry=True)
    first, second = orch.list_job_records(wid)
    assert (first.attempt, first.status, first.error) == (
        1,
        AgentJobStatus.FAILED,
        "transient",
    )
    assert (second.attempt, second.status) == (2, AgentJobStatus.QUEUED)

    claimed = queue.claim_next_task("worker-2", [])
    queue.complete_task(claimed.task_id, "worker-2", {"architecture": {"name": "x"}})
    first, second = orch.list_job_records(wid)
    assert second.status == AgentJobStatus.SUCCEEDED
    assert second.agent.worker_id == "worker-2"


def test_job_records_survive_snapshot_restore() -> None:
    store = _MemoryStore()
    orch = _orchestrator(state_store=store)
    wid, _, _ = _to_architecture_task(orch)

    restored = _orchestrator(state_store=store)
    assert [j.to_dict() for j in restored.list_job_records(wid)] == [
        j.to_dict() for j in orch.list_job_records(wid)
    ]


def test_legacy_snapshot_without_provenance_binds_on_next_task() -> None:
    store = _MemoryStore()
    orch = _orchestrator(state_store=store)
    wid = orch.start_pipeline(YAML_SPEC, "org-1", "owner")
    # Simulate a snapshot written before provenance and job records existed.
    snapshot = store.snapshot
    snapshot.pop("jobs")
    snapshot["workflows"][wid]["context"].pop("requirements_ref")

    restored = _orchestrator(state_store=store)
    workflow = restored._workflows[wid]
    assert restored.current_requirements_ref(workflow) is None
    gate = next(g for g in workflow.gates if "requirements" in g.name.lower())
    restored.approve_gate(wid, gate.id, "owner")
    restored.advance_pipeline(wid)

    ref = restored.current_requirements_ref(workflow)
    assert ref is not None and ref.revision == 1
    (task,) = restored.list_tasks(wid)
    assert task.metadata["requirements_ref"] == ref.to_dict()


def test_status_response_exposes_job_records() -> None:
    from api.schemas.pipeline import PipelineStatusResponse

    orch = _orchestrator()
    wid, _, task = _to_architecture_task(orch)
    response = PipelineStatusResponse(**orch.get_pipeline_status(wid))
    (job,) = response.jobs
    assert job["task_id"] == task.id
    assert job["requirements"]["requirement_ids"] == ["R1", "R2"]
