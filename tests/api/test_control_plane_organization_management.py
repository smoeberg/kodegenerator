"""Organization management tests across repository, API and runtime context."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from api.auth import User
from api.endpoints.control_plane_organizations import (
    OrganizationCreateRequest,
    OrganizationPatchRequest,
    create_organization,
    list_organizations,
    update_organization,
)
from domain.actor import Actor, ActorType
from domain.organization import Organization
from domain.principal import Principal
from infrastructure.persistence.models import (
    ActorModel,
    OrganizationMembershipModel,
)
from infrastructure.persistence.repositories import OrganizationRepository
from runtime.core import DORRuntime


@pytest.fixture
def runtime(tmp_path) -> DORRuntime:
    database_path = tmp_path / "organizations.db"
    value = DORRuntime(f"sqlite:///{database_path}")
    value.boot()
    return value


def _seed_membership(
    runtime: DORRuntime,
    *,
    username: str,
    organization_id: str,
    is_admin: bool,
) -> None:
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


def _seed_organization(
    runtime: DORRuntime,
    *,
    organization_id: str,
    name: str,
    username: str,
    is_admin: bool,
) -> None:
    runtime.create_organization(Organization(id=organization_id, name=name))
    runtime.register_actor(
        Actor(id=username, type=ActorType.HUMAN, identity=username),
        organization_id=organization_id,
    )
    _seed_membership(
        runtime,
        username=username,
        organization_id=organization_id,
        is_admin=is_admin,
    )


def _user(username: str = "alice", organization_id: str = "org-a") -> User:
    return User(
        username=username,
        organization_id=organization_id,
        full_name="Alice Admin",
    )


def test_organization_repository_list_is_stable(runtime: DORRuntime) -> None:
    runtime.create_organization(Organization(id="z-org", name="Zulu"))
    runtime.create_organization(Organization(id="a-org", name="Alpha"))
    runtime.create_organization(Organization(id="a-org-2", name="Alpha"))

    with runtime.database.session() as session:
        organizations = OrganizationRepository(session).list()

    assert [(item.name, item.id) for item in organizations] == [
        ("Alpha", "a-org"),
        ("Alpha", "a-org-2"),
        ("Zulu", "z-org"),
    ]


def test_list_organizations_returns_only_authenticated_memberships(
    runtime: DORRuntime,
) -> None:
    _seed_organization(
        runtime,
        organization_id="org-a",
        name="Alpha",
        username="alice",
        is_admin=True,
    )
    _seed_organization(
        runtime,
        organization_id="org-b",
        name="Beta",
        username="alice",
        is_admin=False,
    )
    _seed_organization(
        runtime,
        organization_id="org-secret",
        name="Secret",
        username="bob",
        is_admin=True,
    )

    result = list_organizations(current_user=_user(), dor=runtime)

    assert result.active_organization_id == "org-a"
    assert [(item.id, item.is_admin) for item in result.organizations] == [
        ("org-a", True),
        ("org-b", False),
    ]
    assert "org-secret" not in {item.id for item in result.organizations}


def test_create_organization_adds_admin_membership_and_runtime_actor(
    runtime: DORRuntime,
) -> None:
    _seed_organization(
        runtime,
        organization_id="org-a",
        name="Alpha",
        username="alice",
        is_admin=True,
    )

    created = create_organization(
        OrganizationCreateRequest(
            id="org-b",
            name="Beta Platform",
            description="Second governed tenant",
        ),
        current_user=_user(),
        dor=runtime,
    )

    assert created.id == "org-b"
    assert created.name == "Beta Platform"
    assert created.is_admin is True

    with runtime.database.session() as session:
        membership = session.get(OrganizationMembershipModel, ("alice", "org-b"))
        actors = list(
            session.scalars(
                select(ActorModel).where(ActorModel.id == "alice")
            ).all()
        )
    assert membership is not None
    assert membership.is_admin is True
    assert {item.organization_id for item in actors} == {"org-a", "org-b"}

    context = runtime.establish_context(
        Principal(id="alice", type="user", metadata={"actor_id": "alice"}),
        organization_id="org-b",
        actor_id="alice",
    )
    assert context.organization_id == "org-b"
    assert context.actor_id == "alice"


def test_create_organization_requires_existing_admin_membership(
    runtime: DORRuntime,
) -> None:
    _seed_organization(
        runtime,
        organization_id="org-a",
        name="Alpha",
        username="alice",
        is_admin=False,
    )

    with pytest.raises(HTTPException) as exc_info:
        create_organization(
            OrganizationCreateRequest(id="org-b", name="Beta"),
            current_user=_user(),
            dor=runtime,
        )

    assert exc_info.value.status_code == 403


def test_update_organization_changes_only_mutable_metadata(
    runtime: DORRuntime,
) -> None:
    _seed_organization(
        runtime,
        organization_id="org-a",
        name="Alpha",
        username="alice",
        is_admin=True,
    )

    updated = update_organization(
        "org-a",
        OrganizationPatchRequest(
            name="Alpha Renamed",
            description="Updated description",
        ),
        current_user=_user(),
        dor=runtime,
    )

    assert updated.id == "org-a"
    assert updated.name == "Alpha Renamed"
    assert updated.description == "Updated description"
    with runtime.database.session() as session:
        persisted = OrganizationRepository(session).get("org-a")
    assert persisted is not None
    assert persisted.id == "org-a"
    assert persisted.name == "Alpha Renamed"


def test_update_organization_requires_admin_on_exact_target(
    runtime: DORRuntime,
) -> None:
    _seed_organization(
        runtime,
        organization_id="org-a",
        name="Alpha",
        username="alice",
        is_admin=True,
    )
    _seed_organization(
        runtime,
        organization_id="org-b",
        name="Beta",
        username="alice",
        is_admin=False,
    )

    with pytest.raises(HTTPException) as exc_info:
        update_organization(
            "org-b",
            OrganizationPatchRequest(name="Forbidden Rename"),
            current_user=_user(),
            dor=runtime,
        )

    assert exc_info.value.status_code == 403
    with runtime.database.session() as session:
        organization = OrganizationRepository(session).get("org-b")
    assert organization is not None
    assert organization.name == "Beta"
