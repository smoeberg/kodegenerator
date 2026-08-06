"""Phase 3 P3-05 tests for the central authorization boundary."""
from pathlib import Path

from domain.actor import Actor, ActorType
from domain.authority import RoleAssignment, RoleDefinition
from domain.organization import Organization
from domain.principal import Principal
from infrastructure.persistence.uow import UnitOfWork
from runtime.core import DORRuntime
from services.authorization_service import AuthorizationService


def _runtime(tmp_path: Path) -> DORRuntime:
    runtime = DORRuntime(f"sqlite:///{tmp_path / 'authorization.db'}")
    runtime.boot()
    return runtime


def _seed(runtime: DORRuntime, organization_id: str = "org-a", actor_id: str = "actor-a") -> None:
    runtime.create_organization(Organization(id=organization_id, name=organization_id))
    runtime.register_actor(
        Actor(id=actor_id, type=ActorType.HUMAN, identity=actor_id),
        organization_id,
    )


def _grant(runtime: DORRuntime, capability: str, *, status: str = "active", role_status: str = "active") -> None:
    role = RoleDefinition(
        id="workflow.operator",
        name="Workflow Operator",
        capabilities=frozenset({capability}),
        status=role_status,
    )
    assignment = RoleAssignment(
        actor_id="actor-a",
        organization_id="org-a",
        role_definition_id=role.id,
        status=status,
    )
    with runtime.database.session() as session:
        with UnitOfWork(session) as uow:
            uow.authority.add_role_definition(role)
            uow.authority.assign_role(assignment)


def _authorize(runtime: DORRuntime, principal_id: str, capability: str, organization_id: str = "org-a"):
    with runtime.database.session() as session:
        uow = UnitOfWork(session)
        return AuthorizationService(uow).authorize(
            Principal(id=principal_id, type="user"),
            actor_id="actor-a",
            organization_id=organization_id,
            capability_id=capability,
        )


def test_granted_capability_allows(tmp_path: Path) -> None:
    runtime = _runtime(tmp_path)
    _seed(runtime)
    _grant(runtime, "workflow.transition")

    decision = _authorize(runtime, "actor-a", "workflow.transition")

    assert decision.allowed is True
    assert decision.reason_code == "capability_granted"


def test_missing_capability_denies(tmp_path: Path) -> None:
    runtime = _runtime(tmp_path)
    _seed(runtime)
    _grant(runtime, "workflow.read")

    decision = _authorize(runtime, "actor-a", "workflow.transition")

    assert decision.allowed is False
    assert decision.reason_code == "capability_not_granted"


def test_inactive_assignment_denies(tmp_path: Path) -> None:
    runtime = _runtime(tmp_path)
    _seed(runtime)
    _grant(runtime, "workflow.transition", status="inactive")

    decision = _authorize(runtime, "actor-a", "workflow.transition")

    assert decision.allowed is False
    assert decision.reason_code == "capability_not_granted"


def test_revoked_assignment_denies(tmp_path: Path) -> None:
    runtime = _runtime(tmp_path)
    _seed(runtime)
    _grant(runtime, "workflow.transition", status="revoked")

    decision = _authorize(runtime, "actor-a", "workflow.transition")

    assert decision.allowed is False
    assert decision.reason_code == "capability_not_granted"


def test_inactive_role_denies(tmp_path: Path) -> None:
    runtime = _runtime(tmp_path)
    _seed(runtime)
    _grant(runtime, "workflow.transition", role_status="inactive")

    decision = _authorize(runtime, "actor-a", "workflow.transition")

    assert decision.allowed is False
    assert decision.reason_code == "capability_not_granted"


def test_wrong_organization_denies(tmp_path: Path) -> None:
    runtime = _runtime(tmp_path)
    _seed(runtime)
    _grant(runtime, "workflow.transition")

    decision = _authorize(runtime, "actor-a", "workflow.transition", "org-b")

    assert decision.allowed is False
    assert decision.reason_code == "actor_not_in_organization"


def test_unknown_actor_denies(tmp_path: Path) -> None:
    runtime = _runtime(tmp_path)
    _seed(runtime)

    with runtime.database.session() as session:
        uow = UnitOfWork(session)
        decision = AuthorizationService(uow).authorize(
            Principal(id="missing", type="user"),
            actor_id="missing",
            organization_id="org-a",
            capability_id="workflow.read",
        )

    assert decision.allowed is False
    assert decision.reason_code == "actor_not_in_organization"


def test_invalid_capability_denies(tmp_path: Path) -> None:
    runtime = _runtime(tmp_path)
    _seed(runtime)

    decision = _authorize(runtime, "actor-a", "workflow-transition")

    assert decision.allowed is False
    assert decision.reason_code == "invalid_capability"


def test_principal_actor_mismatch_denies(tmp_path: Path) -> None:
    runtime = _runtime(tmp_path)
    _seed(runtime)
    _grant(runtime, "workflow.transition")

    decision = _authorize(runtime, "another-principal", "workflow.transition")

    assert decision.allowed is False
    assert decision.reason_code == "principal_actor_mismatch"


def test_decision_is_deterministic_and_contains_audit_context(tmp_path: Path) -> None:
    runtime = _runtime(tmp_path)
    _seed(runtime)
    _grant(runtime, "workflow.transition")

    decision = _authorize(runtime, "actor-a", "workflow.transition")

    assert decision.allowed is True
    assert decision.reason
    assert decision.actor_id == "actor-a"
    assert decision.principal_id == "actor-a"
    assert decision.organization_id == "org-a"
    assert decision.capability_id == "workflow.transition"
