"""Deterministic, provider-neutral routing of frozen Council assignments.

A Council assignment plan freezes the exact bot profile, model deployment,
provider connection, and protocol function for every stage role.  Routing
resolves the durable plan to an opaque provider adapter and never silently
substitutes a replacement: a restarted session with the same plan resolves
the identical adapter or fails closed.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Protocol

from phase4.council.configuration import ProtocolFunction
from phase4.council.roles import CouncilRole, RolePersona
from phase4.verification.allocation_selector import (
    CouncilRunSelection,
    FrozenCouncilAssignment,
)


class CouncilProvider(Protocol):
    """Opaque bounded-turn provider; the orchestrator depends only on this."""

    def deliberate(self, request: Any) -> Any: ...  # pragma: no cover

    @property
    def provider_id(self) -> str: ...  # pragma: no cover


class CouncilProviderFactory(Protocol):
    """Creates a provider adapter bound to an exact snapshot identity."""

    def create(
        self,
        *,
        connection_id: str,
        connection_version: int,
        deployment_id: str,
        deployment_revision: int,
        model_id: str,
        model_family: str,
        prompt_version: str,
        route_fingerprint: str,
    ) -> CouncilProvider: ...  # pragma: no cover


class ProviderRoutingError(RuntimeError):
    """Raised when routing cannot resolve the frozen assignment."""


def _digest(payload: dict[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


@dataclass(frozen=True)
class AssignmentRoute:
    """Deterministic adapter identity for one frozen assignment."""

    assignment_id: str
    role: CouncilRole
    agent_identity: str
    capability: str
    provider_id: str
    connection_id: str
    connection_version: int
    deployment_id: str
    deployment_revision: int
    model_id: str
    model_family: str
    prompt_version: str
    protocol_function: ProtocolFunction
    route_fingerprint: str

    def __post_init__(self) -> None:
        if not self.assignment_id:
            raise ProviderRoutingError("assignment_id must be non-empty")
        if not self.provider_id:
            raise ProviderRoutingError("provider_id must be non-empty")

    @classmethod
    def from_assignment(
        cls,
        assignment: FrozenCouncilAssignment,
        role: CouncilRole,
        persona: RolePersona,
        protocol_function: ProtocolFunction,
        *,
        provider_id: str,
        connection_id: str,
        connection_version: int,
        deployment_id: str,
        deployment_revision: int,
        model_id: str,
        model_family: str,
        prompt_version: str,
    ) -> AssignmentRoute:
        """Build a route from a flat frozen assignment snapshot."""
        identity = {
            "assignment_id": assignment.assignment_id,
            "role": role.value,
            "agent_identity": assignment.agent_identity,
            "capability": persona.capability,
            "provider_id": provider_id,
            "connection_id": connection_id,
            "connection_version": connection_version,
            "deployment_id": deployment_id,
            "deployment_revision": deployment_revision,
            "model_id": model_id,
            "model_family": model_family,
            "prompt_version": prompt_version,
            "protocol_function": protocol_function.value,
        }
        return cls(
            assignment_id=assignment.assignment_id,
            role=role,
            agent_identity=assignment.agent_identity,
            capability=persona.capability,
            provider_id=provider_id,
            connection_id=connection_id,
            connection_version=connection_version,
            deployment_id=deployment_id,
            deployment_revision=deployment_revision,
            model_id=model_id,
            model_family=model_family,
            prompt_version=prompt_version,
            protocol_function=protocol_function,
            route_fingerprint=_digest(identity),
        )


class TemplateCouncilProviderRouter:
    """Resolves every frozen assignment to an exact provider adapter.

    The router owns one provider factory per provider id.  It never consults
    a mutable registry after the plan is built: a restarted turn resolves the
    identical adapter because the plan snapshots are immutable.
    """

    def __init__(
        self,
        factories: dict[str, CouncilProviderFactory],
        *,
        model_lookup: Callable[[str, str, int], dict[str, Any]] | None = None,
    ) -> None:
        if not factories:
            raise ProviderRoutingError("at least one provider factory is required")
        self._factories = dict(factories)
        self._model_lookup = model_lookup or (
            lambda _deployment_id, _revision, _model_id: {}
        )
        self._cache: dict[str, CouncilProvider] = {}

    def resolve(self, route: AssignmentRoute) -> CouncilProvider:
        factory = self._factories.get(route.provider_id)
        if factory is None:
            raise ProviderRoutingError(
                f"no provider factory registered for provider {route.provider_id!r}"
            )
        cached = self._cache.get(route.route_fingerprint)
        if cached is not None:
            return cached
        provider = factory.create(
            connection_id=route.connection_id,
            connection_version=route.connection_version,
            deployment_id=route.deployment_id,
            deployment_revision=route.deployment_revision,
            model_id=route.model_id,
            model_family=route.model_family,
            prompt_version=route.prompt_version,
            route_fingerprint=route.route_fingerprint,
        )
        self._cache[route.route_fingerprint] = provider
        return provider

    def cold_resolve(self, route: AssignmentRoute) -> CouncilProvider:
        """Bypass the warm cache (used by restart/replay paths)."""
        self._cache.pop(route.route_fingerprint, None)
        return self.resolve(route)


@dataclass(frozen=True)
class CouncilAssignmentPlan:
    """Immutable plan: every stage role maps to exactly one frozen assignment."""

    run_id: str
    decision_id: str
    organization_id: str
    template_id: str
    template_version: int
    evaluation_policy_ref: str | None = None
    routes: tuple[AssignmentRoute, ...] = field(default_factory=tuple)
    plan_fingerprint: str = ""

    def __post_init__(self) -> None:
        if not self.run_id:
            raise ProviderRoutingError("run_id must be non-empty")
        if not self.decision_id:
            raise ProviderRoutingError("decision_id must be non-empty")
        if not self.organization_id:
            raise ProviderRoutingError("organization_id must be non-empty")

    @classmethod
    def from_selection(
        cls,
        selection: CouncilRunSelection,
        *,
        roll_for_role: Callable[[str], CouncilRole],
        person_for_role: Callable[[CouncilRole], RolePersona],
        protocol_for_role: Callable[[str], ProtocolFunction],
        model_lookup: Callable[[str, int, str], dict[str, Any]],
    ) -> CouncilAssignmentPlan:
        if selection.status != "selected":
            raise ProviderRoutingError("selection is not frozen")
        routes: list[AssignmentRoute] = []
        for assignment in selection.assignments:
            role = roll_for_role(assignment.stage_id)
            persona = person_for_role(role)
            protocol = protocol_for_role(assignment.stage_id)
            model = model_lookup(
                assignment.deployment_id,
                assignment.deployment_revision,
                assignment.model_id if hasattr(assignment, "model_id") else "",
            )
            routes.append(
                AssignmentRoute.from_assignment(
                    assignment,
                    role,
                    persona,
                    protocol,
                    provider_id=assignment.connection_id,
                    connection_id=assignment.connection_id,
                    connection_version=assignment.connection_version,
                    deployment_id=assignment.deployment_id,
                    deployment_revision=assignment.deployment_revision,
                    model_id=model.get("model_id") or "",
                    model_family=model.get("model_family") or "",
                    prompt_version=model.get("prompt_version") or "v1",
                )
            )
        identity = {
            "run_id": selection.run_id,
            "decision_id": selection.fingerprint,
            "organization_id": selection.organization_id,
            "template_id": selection.template_id,
            "template_version": selection.template_version,
            "routes": [
                {
                    "assignment_id": route.assignment_id,
                    "role": route.role.value,
                    "agent_identity": route.agent_identity,
                    "provider_id": route.provider_id,
                    "deployment_id": route.deployment_id,
                    "deployment_revision": route.deployment_revision,
                    "model_id": route.model_id,
                    "model_family": route.model_family,
                    "prompt_version": route.prompt_version,
                    "protocol_function": route.protocol_function.value,
                }
                for route in routes
            ],
        }
        return cls(
            run_id=selection.run_id,
            decision_id=selection.fingerprint,
            organization_id=selection.organization_id,
            template_id=selection.template_id,
            template_version=selection.template_version,
            routes=tuple(routes),
            plan_fingerprint=_digest(identity),
        )

    def route_for(self, role: CouncilRole) -> AssignmentRoute:
        matches = [route for route in self.routes if route.role is role]
        if len(matches) != 1:
            raise ProviderRoutingError(
                f"plan must assign exactly one provider to role {role.value}"
            )
        return matches[0]
