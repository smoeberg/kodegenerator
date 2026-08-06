"""Central authorization boundary for Phase 3.

Authorization is evaluated from persisted actor/org identity and the canonical
RoleAssignment -> RoleDefinition -> Capability resolution path.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from domain.authority import AuthorizationDecision, Capability
from domain.principal import Principal

if TYPE_CHECKING:
    from infrastructure.persistence.uow import UnitOfWork


class AuthorizationService:
    """Deterministic, fail-closed authorization service."""

    def __init__(self, uow: "UnitOfWork") -> None:
        self.uow = uow

    def authorize(
        self,
        principal: Principal,
        actor_id: str,
        organization_id: str,
        capability_id: str,
        resource_id: str | None = None,
        resource_organization_id: str | None = None,
    ) -> AuthorizationDecision:
        """Evaluate one authorization request without implicit fallback.

        When a resource is supplied, its organization must resolve to the
        active organization. Missing and cross-organization resources use the
        same denial so authorization behavior cannot disclose protected
        resource existence.
        """
        base = dict(
            actor_id=actor_id,
            principal_id=principal.id,
            organization_id=organization_id,
            capability_id=capability_id,
            resource_id=resource_id,
        )

        if principal.id != actor_id:
            return AuthorizationDecision(
                allowed=False,
                reason="Principal does not identify the requested actor",
                reason_code="principal_actor_mismatch",
                **base,
            )

        try:
            Capability(capability_id)
        except ValueError:
            return AuthorizationDecision(
                allowed=False,
                reason="Capability is not canonical",
                reason_code="invalid_capability",
                **base,
            )

        if resource_id is not None and resource_organization_id != organization_id:
            return AuthorizationDecision(
                allowed=False,
                reason="Target resource is not accessible in this organization",
                reason_code="resource_not_accessible",
                **base,
            )

        actor = self.uow.actors.get_for_organization(actor_id, organization_id)
        if actor is None:
            return AuthorizationDecision(
                allowed=False,
                reason="Actor is not a member of the organization",
                reason_code="actor_not_in_organization",
                **base,
            )

        if actor.status != "active":
            return AuthorizationDecision(
                allowed=False,
                reason="Actor is not active",
                reason_code="actor_inactive",
                **base,
            )

        effective = self.uow.authority.get_effective_capabilities(
            actor_id, organization_id
        )
        if capability_id not in effective:
            return AuthorizationDecision(
                allowed=False,
                reason="Actor does not hold the requested capability",
                reason_code="capability_not_granted",
                **base,
            )

        return AuthorizationDecision(
            allowed=True,
            reason="Capability granted by effective role authority",
            reason_code="capability_granted",
            **base,
        )
