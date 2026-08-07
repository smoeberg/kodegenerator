"""Pure Phase 3 role-to-capability resolution."""
from __future__ import annotations

from collections.abc import Iterable, Mapping

from domain.authority import RoleAssignment, RoleDefinition


def resolve_effective_capabilities(actor_id: str, organization_id: str, assignments: Iterable[RoleAssignment], roles: Mapping[str, RoleDefinition]) -> frozenset[str]:
    """Return effective capabilities only from active same-organization authority."""
    if not actor_id or not organization_id:
        return frozenset()
    effective: set[str] = set()
    for assignment in assignments:
        if assignment.actor_id != actor_id or assignment.organization_id != organization_id or assignment.status != "active":
            continue
        role = roles.get(assignment.role_definition_id)
        if role is None or role.organization_id != organization_id or role.status != "active":
            continue
        effective.update(role.capabilities)
    return frozenset(effective)
