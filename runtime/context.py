"""Authenticated identity and organization-scoped runtime context."""
from __future__ import annotations

from dataclasses import dataclass

from domain.actor import Actor
from domain.organization import Organization
from domain.principal import Principal


class ContextError(RuntimeError):
    """Raised when an authenticated context cannot be established safely."""


@dataclass(frozen=True)
class OrganizationContext:
    """The security boundary carried by every organization-scoped operation."""

    principal: Principal
    actor: Actor
    organization: Organization

    @property
    def organization_id(self) -> str:
        return self.organization.id

    @property
    def actor_id(self) -> str:
        return self.actor.id


def establish_context(
    principal: Principal,
    actor: Actor,
    organization: Organization,
) -> OrganizationContext:
    """Bind an authenticated Principal to an Actor and Organization.

    The actor binding is explicit: the validated Principal id must equal the
    Actor id, or a trusted ``actor_id`` claim must name the Actor. The actor
    must also belong to the requested organization and be active.
    """
    claimed_actor_id = principal.metadata.get("actor_id", principal.id)
    if claimed_actor_id != actor.id:
        raise ContextError("Authenticated Principal is not bound to the requested Actor")
    if actor.organization is not None and actor.organization.id != organization.id:
        raise ContextError("Actor does not belong to the requested organization")
    if actor.status != "active":
        raise ContextError("Actor is not active")
    return OrganizationContext(principal=principal, actor=actor, organization=organization)
