"""Provider-neutral routing for immutable Council assignment snapshots."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Any, Protocol

from phase4.council.configuration import ProtocolFunction
from phase4.council.roles import CouncilRole, RolePersona
from phase4.verification.allocation_selector import (
    CouncilRunSelection,
    FrozenCouncilAssignment,
)

_SHA256 = re.compile(r"^[a-f0-9]{64}$")


class CouncilProvider(Protocol):
    @property
    def provider_id(self) -> str: ...

    def deliberate(self, request: Any) -> Any: ...


class CouncilProviderFactory(Protocol):
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
    ) -> CouncilProvider: ...


class CouncilProviderRouter(Protocol):
    def resolve(self, route: AssignmentRoute) -> CouncilProvider: ...


class RouteCatalogResolver(Protocol):
    def resolve(self, assignment: FrozenCouncilAssignment) -> CatalogRouteSnapshot: ...


class ProviderRoutingError(RuntimeError):
    """The frozen assignment cannot be resolved without substitution."""


def _digest(payload: Any) -> str:
    return hashlib.sha256(
        json.dumps(
            payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False
        ).encode("utf-8")
    ).hexdigest()


@dataclass(frozen=True)
class CatalogRouteSnapshot:
    """Exact immutable catalog material required to invoke one model."""

    provider_id: str
    connection_id: str
    connection_version: int
    connection_fingerprint: str
    deployment_id: str
    deployment_revision: int
    deployment_fingerprint: str
    model_id: str
    model_family: str
    prompt_version: str

    def __post_init__(self) -> None:
        if not self.provider_id.strip() or not self.model_id.strip():
            raise ProviderRoutingError("catalog route identity is incomplete")
        if min(self.connection_version, self.deployment_revision) < 1:
            raise ProviderRoutingError("catalog route versions must be positive")
        if not _SHA256.fullmatch(self.connection_fingerprint):
            raise ProviderRoutingError("connection fingerprint is invalid")
        if not _SHA256.fullmatch(self.deployment_fingerprint):
            raise ProviderRoutingError("deployment fingerprint is invalid")


@dataclass(frozen=True)
class AssignmentRoute:
    """One role bound to one complete, immutable provider route."""

    assignment_id: str
    stage_id: str
    role: CouncilRole
    agent_identity: str
    capability: str
    protocol_function: ProtocolFunction
    bot_profile_id: str
    bot_profile_version: int
    profile_fingerprint: str
    provider_id: str
    connection_id: str
    connection_version: int
    connection_fingerprint: str
    deployment_id: str
    deployment_revision: int
    deployment_fingerprint: str
    model_id: str
    model_family: str
    prompt_version: str
    route_fingerprint: str

    def turn_binding(self):
        from phase4.council.roles import CouncilTurnRouteBinding

        return CouncilTurnRouteBinding(
            assignment_id=self.assignment_id,
            route_fingerprint=self.route_fingerprint,
            connection_id=self.connection_id,
            connection_version=self.connection_version,
            deployment_id=self.deployment_id,
            deployment_revision=self.deployment_revision,
            model_id=self.model_id,
            model_family=self.model_family,
            prompt_version=self.prompt_version,
            role=self.role,
            protocol_function=self.protocol_function,
            agent_identity=self.agent_identity,
        )

    @classmethod
    def from_assignment(
        cls,
        assignment: FrozenCouncilAssignment,
        *,
        role: CouncilRole,
        persona: RolePersona,
        protocol_function: ProtocolFunction,
        catalog: CatalogRouteSnapshot,
    ) -> AssignmentRoute:
        if (
            catalog.connection_id != assignment.connection_id
            or catalog.connection_version != assignment.connection_version
            or catalog.connection_fingerprint != assignment.connection_fingerprint
            or catalog.deployment_id != assignment.deployment_id
            or catalog.deployment_revision != assignment.deployment_revision
            or catalog.deployment_fingerprint != assignment.deployment_fingerprint
        ):
            raise ProviderRoutingError(
                "catalog snapshot does not match the frozen assignment"
            )
        identity = {
            "assignment_id": assignment.assignment_id,
            "stage_id": assignment.stage_id,
            "role": role.value,
            "agent_identity": assignment.agent_identity,
            "capability": persona.capability,
            "protocol_function": protocol_function.value,
            "bot_profile_id": assignment.bot_profile_id,
            "bot_profile_version": assignment.bot_profile_version,
            "profile_fingerprint": assignment.profile_fingerprint,
            **catalog.__dict__,
        }
        return cls(
            assignment_id=assignment.assignment_id,
            stage_id=assignment.stage_id,
            role=role,
            agent_identity=assignment.agent_identity,
            capability=persona.capability,
            protocol_function=protocol_function,
            bot_profile_id=assignment.bot_profile_id,
            bot_profile_version=assignment.bot_profile_version,
            profile_fingerprint=assignment.profile_fingerprint,
            provider_id=catalog.provider_id,
            connection_id=catalog.connection_id,
            connection_version=catalog.connection_version,
            connection_fingerprint=catalog.connection_fingerprint,
            deployment_id=catalog.deployment_id,
            deployment_revision=catalog.deployment_revision,
            deployment_fingerprint=catalog.deployment_fingerprint,
            model_id=catalog.model_id,
            model_family=catalog.model_family,
            prompt_version=catalog.prompt_version,
            route_fingerprint=_digest(identity),
        )


@dataclass(frozen=True)
class CouncilAssignmentPlan:
    run_id: str
    decision_id: str
    organization_id: str
    template_id: str
    template_version: int
    routes: tuple[AssignmentRoute, ...]
    plan_fingerprint: str

    def __post_init__(self) -> None:
        if not self.run_id.strip() or not self.organization_id.strip():
            raise ProviderRoutingError("assignment plan identity is incomplete")
        if not _SHA256.fullmatch(self.decision_id):
            raise ProviderRoutingError("decision ID must be a SHA-256 fingerprint")
        if self.template_version < 1 or not self.routes:
            raise ProviderRoutingError("assignment plan must contain routes")
        identities = [route.assignment_id for route in self.routes]
        if len(set(identities)) != len(identities):
            raise ProviderRoutingError("assignment plan contains duplicate assignments")
        expected = self._fingerprint(
            self.decision_id,
            self.organization_id,
            self.template_id,
            self.template_version,
            self.routes,
        )
        if self.plan_fingerprint != expected:
            raise ProviderRoutingError("assignment plan fingerprint is invalid")

    @classmethod
    def from_selection(
        cls,
        selection: CouncilRunSelection,
        *,
        role_for_stage,
        persona_for_role,
        protocol_for_stage,
        catalog_resolver: RouteCatalogResolver,
    ) -> CouncilAssignmentPlan:
        if selection.status != "selected" or not selection.assignments:
            raise ProviderRoutingError("selection is not selected and frozen")
        routes = tuple(
            AssignmentRoute.from_assignment(
                assignment,
                role=role_for_stage(assignment.stage_id),
                persona=persona_for_role(role_for_stage(assignment.stage_id)),
                protocol_function=protocol_for_stage(assignment.stage_id),
                catalog=catalog_resolver.resolve(assignment),
            )
            for assignment in selection.assignments
        )
        plan_fingerprint = cls._fingerprint(
            selection.fingerprint,
            selection.organization_id,
            selection.template_id,
            selection.template_version,
            routes,
        )
        return cls(
            run_id=selection.run_id,
            decision_id=selection.fingerprint,
            organization_id=selection.organization_id,
            template_id=selection.template_id,
            template_version=selection.template_version,
            routes=routes,
            plan_fingerprint=plan_fingerprint,
        )

    @staticmethod
    def _fingerprint(
        decision_id: str,
        organization_id: str,
        template_id: str,
        template_version: int,
        routes: tuple[AssignmentRoute, ...],
    ) -> str:
        return _digest(
            {
                "decision_id": decision_id,
                "organization_id": organization_id,
                "template_id": template_id,
                "template_version": template_version,
                "routes": [route.__dict__ for route in routes],
            }
        )

    def route_for(self, role: CouncilRole) -> AssignmentRoute:
        matches = tuple(route for route in self.routes if route.role is role)
        if len(matches) != 1:
            raise ProviderRoutingError(
                f"plan must assign exactly one provider to role {role.value}"
            )
        return matches[0]


class TemplateCouncilProviderRouter:
    """Resolve the exact configured connection; never choose a fallback."""

    def __init__(self, factories: dict[str, CouncilProviderFactory]) -> None:
        if not factories:
            raise ProviderRoutingError("at least one provider factory is required")
        self._factories = dict(factories)
        self._cache: dict[str, CouncilProvider] = {}

    def resolve(self, route: AssignmentRoute) -> CouncilProvider:
        cached = self._cache.get(route.route_fingerprint)
        if cached is not None:
            return cached
        factory = self._factories.get(route.provider_id)
        if factory is None:
            raise ProviderRoutingError(
                f"no provider factory registered for {route.provider_id!r}"
            )
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
        if getattr(provider, "provider_id", None) != route.provider_id:
            raise ProviderRoutingError("provider identity does not match frozen route")
        self._cache[route.route_fingerprint] = provider
        return provider
