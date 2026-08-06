"""Phase 3 P3-04 tests for effective role capability resolution."""
from domain.authority import RoleAssignment, RoleDefinition
from domain.authority_resolution import resolve_effective_capabilities


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


def _role(role_id: str, *capabilities: str, status: str = "active") -> RoleDefinition:
    return RoleDefinition(
        id=role_id,
        name=role_id,
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
        "other-org": _role("other-org", "workflow.approve"),
        "valid": _role("valid", "workflow.read"),
    }
    assert resolve_effective_capabilities("actor-a", "org-a", assignments, roles) == frozenset(
        {"workflow.read"}
    )


def test_actor_with_no_assignments_has_no_capabilities() -> None:
    assert resolve_effective_capabilities("actor-a", "org-a", [], {}) == frozenset()
