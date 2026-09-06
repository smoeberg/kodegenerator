"""Regression coverage for the pipeline tenant-isolation security boundary."""

from __future__ import annotations

from fastapi import HTTPException
from sqlalchemy import select

from api.auth import User
from api.endpoints.pipeline import _pipeline_context
from domain.actor import Actor, ActorType
from domain.organization import Organization
from infrastructure.persistence.models import PipelineRuntimeStateModel
from runtime.core import DORRuntime
from runtime.pipeline_registry import get_pipeline_registry, reset_pipeline_registry

_REQUIREMENTS = """
project_name: tenant-isolation
project_description: prove pipeline tenant isolation
requirements:
  - id: REQ-001
    description: isolate pipeline state
    acceptance_criteria:
      - tenant state never crosses organization boundaries
"""


def _runtime(tmp_path, monkeypatch) -> DORRuntime:
    database_url = f"sqlite:///{tmp_path / 'tenant-isolation.db'}"
    monkeypatch.setenv("DOR_ENV", "development")
    monkeypatch.setenv("DATABASE_URL", database_url)
    monkeypatch.setenv("DOR_PIPELINE_DATABASE_URL", database_url)
    monkeypatch.setenv("DOR_QUEUE_BACKEND", "database")
    monkeypatch.delenv("DOR_PIPELINE_STATE_ORGANIZATION_ID", raising=False)
    reset_pipeline_registry()
    runtime = DORRuntime(database_url)
    runtime.boot()
    return runtime


def _seed_identity(runtime: DORRuntime) -> None:
    for organization_id in ("org-a", "org-b"):
        runtime.create_organization(
            Organization(id=organization_id, name=organization_id)
        )
    runtime.register_actor(
        Actor(id="alice", type=ActorType.HUMAN, identity="alice"),
        organization_id="org-a",
    )
    runtime.register_actor(
        Actor(id="bob", type=ActorType.HUMAN, identity="bob"),
        organization_id="org-b",
    )


def test_pipeline_context_rejects_cross_tenant_membership(tmp_path, monkeypatch) -> None:
    runtime = _runtime(tmp_path, monkeypatch)
    _seed_identity(runtime)
    alice = User(username="alice", organization_id="org-a")

    context = _pipeline_context(runtime, alice, "org-a")
    assert context.organization_id == "org-a"

    try:
        _pipeline_context(runtime, alice, "org-b")
    except HTTPException as exc:
        assert exc.status_code == 403
        assert exc.detail == "Organization access denied"
    else:
        raise AssertionError("cross-tenant pipeline context was accepted")


def test_database_pipeline_registry_queue_and_snapshot_are_tenant_isolated(
    tmp_path, monkeypatch
) -> None:
    runtime = _runtime(tmp_path, monkeypatch)

    registry_a = get_pipeline_registry(runtime, organization_id="org-a")
    registry_b = get_pipeline_registry(runtime, organization_id="org-b")
    assert registry_a is not registry_b

    workflow_a = registry_a.orchestrator.start_pipeline(
        _REQUIREMENTS,
        organization_id="org-a",
        created_by="alice",
    )
    registry_a.orchestrator.decide_gate(
        workflow_a,
        "gate_requirements_approval",
        approver="alice",
        decision="approved",
    )
    workflow_b = registry_b.orchestrator.start_pipeline(
        _REQUIREMENTS,
        organization_id="org-b",
        created_by="bob",
    )

    assert registry_a.orchestrator._get_workflow(workflow_b) is None
    assert registry_b.orchestrator._get_workflow(workflow_a) is None
    assert registry_a.queue.pending_count() == 1
    assert registry_b.queue.pending_count() == 0
    assert registry_b.queue.claim_next_task("worker-b", ["domain", "arch"]) is None

    with runtime.database.session() as session:
        rows = session.scalars(
            select(PipelineRuntimeStateModel).order_by(
                PipelineRuntimeStateModel.organization_id
            )
        ).all()
    assert [row.organization_id for row in rows] == ["org-a", "org-b"]
    assert all(row.store_id == "pipeline-default" for row in rows)

    # Simulate independent API/worker process recreation from durable state.
    reset_pipeline_registry()
    restored_a = get_pipeline_registry(runtime, organization_id="org-a")
    restored_b = get_pipeline_registry(runtime, organization_id="org-b")

    assert restored_a.orchestrator._get_workflow(workflow_a) is not None
    assert restored_a.orchestrator._get_workflow(workflow_b) is None
    assert restored_b.orchestrator._get_workflow(workflow_b) is not None
    assert restored_b.orchestrator._get_workflow(workflow_a) is None
    assert restored_a.queue.pending_count() == 1
    assert restored_b.queue.pending_count() == 0


def test_production_registry_access_without_tenant_fails_closed(
    tmp_path, monkeypatch
) -> None:
    runtime = _runtime(tmp_path, monkeypatch)
    reset_pipeline_registry()
    monkeypatch.setenv("DOR_ENV", "production")

    try:
        get_pipeline_registry(runtime)
    except RuntimeError as exc:
        assert "requires explicit organization_id" in str(exc)
    else:
        raise AssertionError("production pipeline registry accepted missing tenant scope")
