"""Security contracts for Control Plane admin authority and project creation."""

from __future__ import annotations

import inspect
from datetime import datetime, timezone

import pytest
from fastapi import HTTPException

from api.auth import User
from api.endpoints.control_plane import create_project
from api.models import ControlPlaneCreateProjectRequest, ControlPlaneIntentInput
from domain.actor import Actor, ActorType
from domain.authority import AuthorizationDecision
from domain.organization import Organization
from infrastructure.persistence.authority_repositories import AuthorityRepository
from infrastructure.persistence.models import OrganizationMembershipModel
from runtime.core import DORRuntime
from services.authorization_service import AuthorizationService
from services.control_plane_admin_authority import (
    managed_admin_role_id,
    sync_control_plane_admin_membership,
)


@pytest.fixture
def runtime(tmp_path) -> DORRuntime:
    value = DORRuntime(f"sqlite:///{tmp_path / 'admin-authority.db'}")
    value.boot()
    return value


def _seed_org(
    runtime: DORRuntime,
    *,
    organization_id: str,
    username: str,
    is_admin: bool,
) -> None:
    runtime.create_organization(
        Organization(id=organization_id, name=f"Organization {organization_id}")
    )
    runtime.register_actor(
        Actor(id=username, type=ActorType.HUMAN, identity=username),
        organization_id=organization_id,
    )
    now = datetime.now(timezone.utc)
    with runtime.database.session() as session:
        session.add(
            OrganizationMembershipModel(
                username=username,
                organization_id=organization_id,
                is_admin=is_admin,
                created_at=now,
                updated_at=now,
            )
        )
        session.commit()


def _user(username: str = "alice", organization_id: str = "org-a") -> User:
    return User(username=username, organization_id=organization_id, full_name=username)


def _request(organization_id: str, command_id: str) -> ControlPlaneCreateProjectRequest:
    return ControlPlaneCreateProjectRequest(
        organization_id=organization_id,
        command_id=command_id,
        name=f"Project {command_id}",
        description="Authority contract test",
        intent=ControlPlaneIntentInput(
            goal="Verify tenant-scoped project creation",
            description="",
            priority="medium",
            constraints={},
            required_capabilities=[],
        ),
    )


def _assignment(runtime: DORRuntime, username: str, organization_id: str):
    role_id = managed_admin_role_id(organization_id)
    with runtime.database.session(organization_id) as session:
        return AuthorityRepository(session).get_assignment(
            username, organization_id, role_id
        )


def test_organization_admin_project_create_is_allowed_through_canonical_authority(
    runtime: DORRuntime,
) -> None:
    _seed_org(runtime, organization_id="org-a", username="alice", is_admin=True)

    result = create_project(
        _request("org-a", "cmd-admin-create"),
        current_user=_user(),
        dor=runtime,
    )

    assert result.project.organization_id == "org-a"
    assert result.project.created_by == "alice"
    assignment = _assignment(runtime, "alice", "org-a")
    assert assignment is not None
    assert assignment.status == "active"

    with runtime.database.session("org-a") as session:
        role = AuthorityRepository(session).get_role_definition(
            managed_admin_role_id("org-a"), "org-a"
        )
    assert role is not None
    assert "project.create" in role.capabilities


def test_ordinary_user_project_create_is_denied(runtime: DORRuntime) -> None:
    _seed_org(runtime, organization_id="org-a", username="alice", is_admin=False)

    with pytest.raises(HTTPException) as exc_info:
        create_project(
            _request("org-a", "cmd-non-admin-create"),
            current_user=_user(),
            dor=runtime,
        )

    assert exc_info.value.status_code == 403
    assert exc_info.value.detail["reason_code"] == "capability_not_granted"
    assert _assignment(runtime, "alice", "org-a") is None


def test_admin_in_organization_a_cannot_create_project_in_organization_b(
    runtime: DORRuntime,
) -> None:
    _seed_org(runtime, organization_id="org-a", username="alice", is_admin=True)
    _seed_org(runtime, organization_id="org-b", username="alice", is_admin=False)

    with pytest.raises(HTTPException) as exc_info:
        create_project(
            _request("org-b", "cmd-cross-tenant-create"),
            current_user=_user(organization_id="org-a"),
            dor=runtime,
        )

    assert exc_info.value.status_code == 403
    assert exc_info.value.detail["reason_code"] == "capability_not_granted"
    assert _assignment(runtime, "alice", "org-b") is None


def test_admin_demotion_inactivates_only_dor_managed_assignment(
    runtime: DORRuntime,
) -> None:
    _seed_org(runtime, organization_id="org-a", username="alice", is_admin=True)
    assert (
        sync_control_plane_admin_membership(
            runtime.database, username="alice", organization_id="org-a"
        )
        is True
    )
    assignment = _assignment(runtime, "alice", "org-a")
    assert assignment is not None
    assert assignment.status == "active"

    with runtime.database.session() as session:
        membership = session.get(OrganizationMembershipModel, ("alice", "org-a"))
        assert membership is not None
        membership.is_admin = False
        membership.updated_at = datetime.now(timezone.utc)
        session.commit()

    assert (
        sync_control_plane_admin_membership(
            runtime.database, username="alice", organization_id="org-a"
        )
        is False
    )
    assignment = _assignment(runtime, "alice", "org-a")
    assert assignment is not None
    assert assignment.status == "inactive"


def test_admin_membership_never_bypasses_canonical_authorization(
    runtime: DORRuntime,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _seed_org(runtime, organization_id="org-a", username="alice", is_admin=True)
    calls: list[str] = []

    def deny(
        self,
        principal,
        actor_id,
        organization_id,
        capability_id,
        resource_id=None,
        resource_organization_id=None,
    ):
        calls.append(capability_id)
        return AuthorizationDecision(
            allowed=False,
            reason="Forced canonical denial for contract verification",
            reason_code="capability_not_granted",
            actor_id=actor_id,
            principal_id=principal.id,
            organization_id=organization_id,
            capability_id=capability_id,
            resource_id=resource_id,
            resource_organization_id=resource_organization_id,
        )

    monkeypatch.setattr(AuthorizationService, "authorize", deny)

    with pytest.raises(HTTPException) as exc_info:
        create_project(
            _request("org-a", "cmd-canonical-denial"),
            current_user=_user(),
            dor=runtime,
        )

    assert exc_info.value.status_code == 403
    assert calls == ["project.create"]

    source = inspect.getsource(create_project)
    assert "sync_control_plane_admin_membership" in source
    assert "dor.projects.create_project" in source
    assert "if is_admin" not in source
