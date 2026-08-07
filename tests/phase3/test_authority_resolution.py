"""Phase 3 P3-04 tests for effective role capability resolution."""
from pathlib import Path

from domain.actor import Actor, ActorType
from domain.authority import RoleAssignment, RoleDefinition
from domain.authority_resolution import resolve_effective_capabilities
from domain.organization import Organization
from runtime.core import DORRuntime


def _assignment(
    role_id: str,
    *,
    actor_id: str = "actor-a",
    organization_id: str = "org-a",
    status: str = "active",
) -> RoleAssignment:
    return RoleAssignment(
        actor_id=actor_id,
        organization_id=organization_id,
        role_definition_id=role_id,
        status=status,
    )


def _role(
    role_id: str,
    *capabilities: str,
    organization_id: str = "org-a",
    status: str = "active",
) -> RoleDefinition:
    return RoleDefinition(
        id=role_id,
        name=role_id,
        organization_id=organization_id,
        capabilities=frozenset(capabilities),
        status=status,
    )


def test_active_role_grants_capabilities() -> None:
    result = resolve_effective_capabilities(
        "actor-a",
        "org-a",
        [_assignment("operator")],
        {"operator": _role("operator", "workflow.read", "workflow.transition")},
    )
    assert result == frozenset({"workflow.read", "workflow.transition"})


def test_inactive_and_revoked_assignments_grant_nothing() -> None:
    assignments = [
        _assignment("inactive", status="inactive"),
        _assignment("revoked", status="revoked"),
    ]
    roles = {
        "inactive": _role("inactive", "workflow.read"),
        "revoked": _role("revoked", "workflow.transition"),
    }
    assert resolve_effective_capabilities("actor-a", "org-a", assignments, roles) == frozenset()


def test_multiple_active_roles_form_a_deduplicated_union() -> None:
    assignments = [_assignment("reader"), _assignment("operator"), _assignment("reviewer")]
    roles = {
        "reader": _role("reader", "workflow.read"),
        "operator": _role("operator", "workflow.read", "workflow.transition"),
        "reviewer": _role("reviewer", "workflow.approve"),
    }
    assert resolve_effective_capabilities("actor-a", "org-a", assignments, roles) == frozenset(
        {"workflow.read", "workflow.transition", "workflow.approve"}
    )


def test_inactive_role_and_missing_role_grant_nothing() -> None:
    assignments = [_assignment("disabled"), _assignment("missing")]
    roles = {"disabled": _role("disabled", "workflow.read", status="inactive")}
    assert resolve_effective_capabilities("actor-a", "org-a", assignments, roles) == frozenset()


def test_cross_actor_and_cross_organization_assignments_fail_closed() -> None:
    assignments = [
        _assignment("other-actor", actor_id="actor-b"),
        _assignment("other-org", organization_id="org-b"),
        _assignment("valid"),
    ]
    roles = {
        "other-actor": _role("other-actor", "workflow.release"),
        "other-org": _role("other-org", "workflow.approve", organization_id="org-b"),
        "valid": _role("valid", "workflow.read"),
    }
    assert resolve_effective_capabilities("actor-a", "org-a", assignments, roles) == frozenset(
        {"workflow.read"}
    )


def test_actor_with_no_assignments_has_no_capabilities() -> None:
    assert resolve_effective_capabilities("actor-a", "org-a", [], {}) == frozenset()


def test_repository_resolves_persisted_role_capabilities(tmp_path: Path) -> None:
    runtime = DORRuntime(f"sqlite:///{tmp_path / 'authority-resolution.db'}")
    runtime.boot()
    runtime.create_organization(Organization(id="org-a", name="org-a"))
    runtime.register_actor(
        Actor(id="actor-a", type=ActorType.HUMAN, identity="actor-a"),
        "org-a",
    )

    role = _role("operator", "workflow.read", "workflow.transition")
    with runtime.database.session() as session:
        from infrastructure.persistence.uow import UnitOfWork

        with UnitOfWork(session) as uow:
            uow.authority.add_role_definition(role)
            uow.authority.assign_role(_assignment(role.id))

    with runtime.database.session() as session:
        from infrastructure.persistence.uow import UnitOfWork

        uow = UnitOfWork(session)
        assert uow.authority.get_effective_capabilities("actor-a", "org-a") == frozenset(
            {"workflow.read", "workflow.transition"}
        )
        assert uow.authority.get_effective_capabilities("actor-a", "org-b") == frozenset()
