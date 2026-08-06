"""Phase 3 authority foundation tests: roles and organization-scoped assignments."""
from datetime import datetime, timezone
from pathlib import Path

import pytest
from sqlalchemy.exc import IntegrityError

from domain.actor import Actor, ActorType
from domain.authority import Capability, RoleAssignment, RoleDefinition
from domain.organization import Organization
from runtime.core import DORRuntime


def _runtime(tmp_path: Path) -> DORRuntime:
    runtime = DORRuntime(f"sqlite:///{tmp_path / 'authority.db'}")
    runtime.boot()
    return runtime


def _seed(runtime: DORRuntime, organization_id: str, actor_id: str) -> None:
    runtime.create_organization(Organization(id=organization_id, name=organization_id))
    runtime.register_actor(
        Actor(id=actor_id, type=ActorType.HUMAN, identity=actor_id),
        organization_id,
    )


def test_capability_requires_canonical_name() -> None:
    assert Capability("workflow.transition").id == "workflow.transition"
    with pytest.raises(ValueError):
        Capability("workflow-transition")


def test_role_definition_grants_capability() -> None:
    role = RoleDefinition(
        id="workflow.operator",
        name="Workflow Operator",
        capabilities=frozenset({"workflow.read", "workflow.transition"}),
    )
    assert role.grants("workflow.read") is True
    assert role.grants("workflow.release") is False


def test_role_assignment_is_persisted_and_organization_scoped(tmp_path: Path) -> None:
    runtime = _runtime(tmp_path)
    _seed(runtime, "org-a", "actor-a")

    role = RoleDefinition(
        id="workflow.operator",
        name="Workflow Operator",
        capabilities=frozenset({"workflow.read"}),
    )
    assignment = RoleAssignment(
        actor_id="actor-a",
        organization_id="org-a",
        role_definition_id=role.id,
        created_at=datetime.now(timezone.utc),
    )

    with runtime.database.session() as session:
        from infrastructure.persistence.uow import UnitOfWork

        with UnitOfWork(session) as uow:
            uow.authority.add_role_definition(role)
            uow.authority.assign_role(assignment)

    with runtime.database.session() as session:
        from infrastructure.persistence.uow import UnitOfWork

        uow = UnitOfWork(session)
        assert uow.authority.get_role_definition(role.id) == role
        assert uow.authority.get_assignments("actor-a", "org-a") == [assignment]
        assert uow.authority.get_assignments("actor-a", "org-b") == []


def test_assignment_cannot_reference_missing_role(tmp_path: Path) -> None:
    runtime = _runtime(tmp_path)
    _seed(runtime, "org-a", "actor-a")
    assignment = RoleAssignment(
        actor_id="actor-a",
        organization_id="org-a",
        role_definition_id="missing",
    )

    with runtime.database.session() as session:
        from infrastructure.persistence.uow import UnitOfWork

        with pytest.raises(ValueError, match="Role definition not found"):
            with UnitOfWork(session) as uow:
                uow.authority.assign_role(assignment)
