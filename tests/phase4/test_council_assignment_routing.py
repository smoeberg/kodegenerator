"""Contract tests for frozen Council assignment routing and plans."""

from __future__ import annotations

import pytest

from phase4.council.configuration import ProtocolFunction
from phase4.council.roles import CouncilRole
from phase4.council.routing import (
    CatalogRouteSnapshot,
    CouncilAssignmentPlan,
    ProviderRoutingError,
    TemplateCouncilProviderRouter,
)
from phase4.verification.allocation_selector import (
    CouncilRunSelection,
    FrozenCouncilAssignment,
    SelectionReceipt,
)


def _selection() -> CouncilRunSelection:
    base = dict(
        assignment_id="1" * 64,
        stage_id="propose",
        role_id="proposer",
        role_version=1,
        allocation_id="allocation-1",
        allocation_version=1,
        bot_profile_id="profile-1",
        bot_profile_version=1,
        profile_fingerprint="d" * 64,
        agent_identity="bot-proposer",
        deployment_id="deploy-1",
        deployment_revision=1,
        deployment_fingerprint="e" * 64,
        connection_id="conn-1",
        connection_version=1,
        connection_fingerprint="f" * 64,
        scope_id="scope-1",
        repository="smoeberg/kodegenerator",
        base_sha="0ad88dd637b902c2c06c743d809bdea0f8954ae4",
        input_fingerprint="c" * 64,
    )
    assignment = FrozenCouncilAssignment(**base)
    receipt = SelectionReceipt(
        stage_id="propose",
        role_id="proposer",
        role_version=1,
        allocation_id="allocation-1",
        allocation_version=1,
        bot_profile_id="profile-1",
        bot_profile_version=1,
        accepted=True,
        reason="selected",
        preference_rank=1,
    )
    return CouncilRunSelection(
        run_id="run-1",
        organization_id="org-1",
        template_id="template-1",
        template_version=1,
        template_fingerprint="a" * 64,
        context_fingerprint="b" * 64,
        scope_id="scope-1",
        repository="smoeberg/kodegenerator",
        base_sha="0ad88dd637b902c2c06c743d809bdea0f8954ae4",
        input_fingerprint="c" * 64,
        assignments=(assignment,),
        receipts=(receipt,),
        status="selected",
    )


def _roles(stage_id: str) -> CouncilRole:
    if stage_id == "propose":
        return CouncilRole.PROPOSER
    if stage_id == "architect":
        return CouncilRole.ARCHITECT
    if stage_id == "security":
        return CouncilRole.SECURITY_SKEPTIC
    if stage_id == "qa":
        return CouncilRole.QA_REDTEAM
    raise ValueError(stage_id)


def _personas(role: CouncilRole):
    from phase4.council.roles import ROLE_PERSONAS

    return ROLE_PERSONAS[role]


def _protocols(stage_id: str) -> ProtocolFunction:
    return (
        ProtocolFunction.PROPOSER
        if stage_id == "propose"
        else ProtocolFunction.REVIEWER
    )


class _FakeFactory:
    created: list[str] = []

    def create(self, **kwargs) -> object:
        self.created.append(kwargs["route_fingerprint"])
        return _FakeProvider(kwargs["route_fingerprint"])


class _FakeProvider:
    def __init__(self, fingerprint: str) -> None:
        self.provider_id = "conn-1"
        self.fingerprint = fingerprint

    def deliberate(self, request) -> str:
        return "deliberated"


class _CatalogResolver:
    def resolve(self, assignment):
        return CatalogRouteSnapshot(
            provider_id=assignment.connection_id,
            connection_id=assignment.connection_id,
            connection_version=assignment.connection_version,
            connection_fingerprint=assignment.connection_fingerprint,
            deployment_id=assignment.deployment_id,
            deployment_revision=assignment.deployment_revision,
            deployment_fingerprint=assignment.deployment_fingerprint,
            model_id="model-1",
            model_family="family-1",
            prompt_version="v1",
        )


def test_plan_from_frozen_selection_is_deterministic() -> None:
    selection = _selection()
    plan = CouncilAssignmentPlan.from_selection(
        selection,
        role_for_stage=_roles,
        persona_for_role=_personas,
        protocol_for_stage=_protocols,
        catalog_resolver=_CatalogResolver(),
    )
    assert plan.run_id == "run-1"
    assert plan.decision_id == selection.fingerprint
    assert len(plan.routes) == 1
    route = plan.routes[0]
    assert route.role is CouncilRole.PROPOSER
    assert route.agent_identity == "bot-proposer"
    assert route.connection_id == "conn-1"
    assert route.deployment_id == "deploy-1"
    assert route.route_fingerprint
    # Determinism: same inputs -> same fingerprint
    plan2 = CouncilAssignmentPlan.from_selection(
        selection,
        role_for_stage=_roles,
        persona_for_role=_personas,
        protocol_for_stage=_protocols,
        catalog_resolver=_CatalogResolver(),
    )
    assert plan2.plan_fingerprint == plan.plan_fingerprint
    assert plan2.routes[0].route_fingerprint == route.route_fingerprint


def test_non_frozen_selection_cannot_build_plan() -> None:
    selection = _selection()
    selection = CouncilRunSelection(
        **{
            **selection.__dict__,
            "status": "blocked",
            "assignments": (),
        }
    )
    with pytest.raises(ProviderRoutingError, match="not selected and frozen"):
        CouncilAssignmentPlan.from_selection(
            selection,
            role_for_stage=_roles,
            persona_for_role=_personas,
            protocol_for_stage=_protocols,
            catalog_resolver=_CatalogResolver(),
        )


def test_router_resolves_identical_provider_without_fallback() -> None:
    selection = _selection()
    plan = CouncilAssignmentPlan.from_selection(
        selection,
        role_for_stage=_roles,
        persona_for_role=_personas,
        protocol_for_stage=_protocols,
        catalog_resolver=_CatalogResolver(),
    )
    factory = _FakeFactory()
    router = TemplateCouncilProviderRouter({"conn-1": factory})
    route = plan.route_for(CouncilRole.PROPOSER)
    provider1 = router.resolve(route)
    provider2 = router.resolve(route)
    # Both warm and cold resolve to the SAME identity, never a new fallback
    assert provider1 is provider2


def test_router_fails_closed_for_unregistered_provider() -> None:
    selection = _selection()
    plan = CouncilAssignmentPlan.from_selection(
        selection,
        role_for_stage=_roles,
        persona_for_role=_personas,
        protocol_for_stage=_protocols,
        catalog_resolver=_CatalogResolver(),
    )
    route = plan.route_for(CouncilRole.PROPOSER)
    with pytest.raises(ProviderRoutingError, match="at least one"):
        TemplateCouncilProviderRouter({})
    # even if a router exists without this provider, resolve fails closed
    router2 = TemplateCouncilProviderRouter({"other-provider": _FakeFactory()})
    with pytest.raises(ProviderRoutingError, match="no provider factory"):
        router2.resolve(route)


def test_plan_must_cover_required_role_exactly_once() -> None:
    with pytest.raises(ProviderRoutingError, match="must contain routes"):
        CouncilAssignmentPlan(
            run_id="run-1",
            decision_id="1" * 64,
            organization_id="org-1",
            template_id="template-1",
            template_version=1,
            routes=(),
            plan_fingerprint="2" * 64,
        )
