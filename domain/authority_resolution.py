"""Pure Phase 3 role-to-capability resolution.

This module contains no persistence concerns. It resolves effective capabilities
from organization-scoped role assignments and role definitions.
"""
from __future__ import annotations

from collections.abc import Iterable, Mapping

from domain.authority import RoleAssignment, RoleDefinition


def resolve_effective_capabilities(
    actor_id: str,
    organization_id: str,
    assignments: Iterable[RoleAssignment],
    roles: Mapping[str, RoleDefinition],
) -> frozenset[str]:
    """Return the actor's effective capabilities for an organization.

    Only active assignments referencing active role definitions contribute
    capabilities. Any assignment that does not match the requested actor or
    organization is ignored (fail-closed). Missing role definitions are also
    ignored so resolution cannot accidentally grant authority.
    """
    if not actor_id or not organization_id:
        return frozenset()

    effective: set[str] = set()
    for assignment in assignments:
        if assignment.actor_id != actor_id:
            continue
        if assignment.organization_id != organization_id:
            continue
        if assignment.status != "active":
            continue

        role = roles.get(assignment.role_definition_id)
        if role is None or role.status != "active":
            continue

        effective.update(role.capabilities)

    return frozenset(effective)
