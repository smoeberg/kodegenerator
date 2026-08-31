"""Persistence tests for frozen Council assignment plans."""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from infrastructure.persistence.council_assignment_store import (
    CouncilAssignmentConflictError,
    CouncilAssignmentStore,
)
import infrastructure.persistence.council_configuration_store  # noqa: F401  (registers council_templates)
from infrastructure.persistence.models import Base
from phase4.council.configuration import ProtocolFunction
from phase4.council.roles import CouncilRole
from phase4.council.routing import AssignmentRoute, CouncilAssignmentPlan


def _route(
    role: CouncilRole,
    assignment_id: str,
    agent_identity: str,
) -> AssignmentRoute:
    return AssignmentRoute(
        assignment_id=assignment_id,
        role=role,
        agent_identity=agent_identity,
        capability="council." + role.value,
        provider_id="provider-1",
        connection_id="conn-1",
        connection_version=1,
        deployment_id="deploy-1",
        deployment_revision=1,
        model_id="model-1",
        model_family="model-family-1",
        prompt_version="v1",
        protocol_function=ProtocolFunction.REVIEWER,
        route_fingerprint=f"fp-{assignment_id}",
    )


def _plan() -> CouncilAssignmentPlan:
    return CouncilAssignmentPlan(
        run_id="run-store-1",
        decision_id="decision-store-1",
        organization_id="org-1",
        template_id="template-1",
        template_version=1,
        routes=(
            _route(CouncilRole.PROPOSER, "asg-store-1", "plan-proposer"),
            _route(CouncilRole.ARCHITECT, "asg-store-2", "plan-architect"),
        ),
        plan_fingerprint="fp-plan-store",
    )


def _store(sessions) -> CouncilAssignmentStore:
    def role_for_stage(stage_id: str) -> CouncilRole:
        return CouncilRole.PROPOSER if stage_id == "proposer" else CouncilRole.ARCHITECT

    def persona_for_role(role: CouncilRole):
        from phase4.council.roles import ROLE_PERSONAS

        return ROLE_PERSONAS[role]

    def protocol_for_stage(stage_id: str) -> ProtocolFunction:
        return ProtocolFunction.PROPOSER

    def model_lookup(deployment_id: str, revision: int, model_id: str):
        return {"model_id": "model-1", "model_family": "family-1", "prompt_version": "v1"}

    return CouncilAssignmentStore(
        sessions,
        role_for_stage=role_for_stage,
        persona_for_role=persona_for_role,
        protocol_for_stage=protocol_for_stage,
        model_lookup=model_lookup,
    )


@pytest.fixture
def sessions():
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False, future=True)


def test_save_and_replay_plan_is_identical(sessions) -> None:
    store = _store(sessions)
    plan = _plan()
    store.save_plan(plan)

    # Different store instance on the same DB: replay must be identical.
    replayed = _store(sessions).get_plan("org-1", "run-store-1")
    assert replayed is not None
    assert replayed.run_id == plan.run_id
    assert replayed.decision_id == plan.decision_id
    assert replayed.plan_fingerprint == plan.plan_fingerprint
    assert len(replayed.routes) == 2
    assert [r.role for r in replayed.routes] == [
        CouncilRole.PROPOSER,
        CouncilRole.ARCHITECT,
    ]
    assert [r.agent_identity for r in replayed.routes] == [
        "plan-proposer",
        "plan-architect",
    ]
    assert replayed.routes[0].route_fingerprint == plan.routes[0].route_fingerprint


def test_empty_plan_rejected(sessions) -> None:
    store = _store(sessions)
    empty = CouncilAssignmentPlan(
        run_id="run-empty",
        decision_id="decision-empty",
        organization_id="org-1",
        template_id="template-1",
        template_version=1,
        routes=(),
        plan_fingerprint="fp-empty",
    )
    with pytest.raises(Exception, match="empty assignment plan"):
        store.save_plan(empty)


def test_missing_plan_returns_none(sessions) -> None:
    store = _store(sessions)
    assert store.get_plan("org-1", "run-missing") is None
