"""Tenant/project isolation tests for the Decision Engine HTTP boundary."""
from __future__ import annotations

import pytest
from fastapi import HTTPException

from api.auth import User
from api.endpoints import decisions as decision_api
from api.endpoints.decisions import CreateDecisionRequest, ResolveDecisionRequest
from domain.actor import Actor, ActorType
from domain.decision import DecisionAlternative
from domain.organization import Organization
from domain.project import Project, ProjectIntent
from infrastructure.persistence.uow import UnitOfWork
from runtime.core import DORRuntime
from services.decision_gate_service import DecisionGateService


def _runtime(tmp_path) -> DORRuntime:
    runtime = DORRuntime(f"sqlite:///{tmp_path / 'decision-scope.db'}")
    runtime.boot()
    for organization_id, username, project_id in (
        ("org-a", "alice", "project-a"),
        ("org-b", "bob", "project-b"),
    ):
        runtime.create_organization(
            Organization(id=organization_id, name=organization_id)
        )
        runtime.register_actor(
            Actor(id=username, type=ActorType.HUMAN, identity=username),
            organization_id,
        )
        with runtime.database.session(organization_id) as session:
            with UnitOfWork(session) as uow:
                uow.projects.add(
                    Project.create(
                        project_id=project_id,
                        organization_id=organization_id,
                        name=project_id,
                        description="Decision scope fixture",
                        intent=ProjectIntent(goal="Exercise decision tenant isolation."),
                        actor_id=username,
                    )
                )
    return runtime


def _request(project_id: str) -> CreateDecisionRequest:
    return CreateDecisionRequest(
        project_id=project_id,
        category="ARCHITECTURE",
        question="Which direction should the case take?",
        alternatives=[
            DecisionAlternative(key="A", title="Option A"),
            DecisionAlternative(key="B", title="Option B"),
        ],
        provenance_id=f"prov-{project_id}",
        risk_level="HIGH",
    )


@pytest.fixture(autouse=True)
def isolated_decision_service(monkeypatch):
    service = DecisionGateService()
    monkeypatch.setattr(decision_api, "_service", service)
    return service


def test_pending_decisions_are_filtered_server_side_by_project_and_tenant(tmp_path) -> None:
    runtime = _runtime(tmp_path)
    alice = User(username="alice", organization_id="org-a")
    bob = User(username="bob", organization_id="org-b")

    own = decision_api.create_decision(_request("project-a"), alice, runtime).decision
    decision_api.create_decision(_request("project-b"), bob, runtime)

    project_pending = decision_api.get_pending_decisions(
        project_id="project-a",
        current_user=alice,
        dor=runtime,
    )
    tenant_pending = decision_api.get_pending_decisions(
        project_id=None,
        current_user=alice,
        dor=runtime,
    )

    assert [item.decision_id for item in project_pending] == [own.decision_id]
    assert [item.decision_id for item in tenant_pending] == [own.decision_id]


def test_cross_tenant_decision_creation_is_rejected_without_disclosure(tmp_path) -> None:
    runtime = _runtime(tmp_path)
    alice = User(username="alice", organization_id="org-a")

    with pytest.raises(HTTPException) as exc_info:
        decision_api.create_decision(_request("project-b"), alice, runtime)

    assert exc_info.value.status_code == 404
    assert exc_info.value.detail == "project_not_found"


def test_cross_tenant_decision_detail_and_resolution_are_rejected(tmp_path) -> None:
    runtime = _runtime(tmp_path)
    alice = User(username="alice", organization_id="org-a")
    bob = User(username="bob", organization_id="org-b")
    foreign = decision_api.create_decision(_request("project-b"), bob, runtime).decision

    with pytest.raises(HTTPException) as detail_error:
        decision_api.get_decision(foreign.decision_id, alice, runtime)
    assert detail_error.value.status_code == 404

    with pytest.raises(HTTPException) as resolve_error:
        decision_api.resolve_decision(
            foreign.decision_id,
            ResolveDecisionRequest(selected_alternative="A", rationale="Not mine"),
            alice,
            runtime,
        )
    assert resolve_error.value.status_code == 404

    still_pending = decision_api.get_pending_decisions(
        project_id="project-b",
        current_user=bob,
        dor=runtime,
    )
    assert [item.decision_id for item in still_pending] == [foreign.decision_id]
