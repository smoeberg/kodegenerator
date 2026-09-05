"""API contract tests for the governed onboarding Control Plane entrypoint."""
from __future__ import annotations

from datetime import datetime, timezone

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from api.auth import User
from api.endpoints.onboarding import declare_onboarding_intent
from api.onboarding_contracts import OnboardingIntentDeclareRequest
from domain.actor import Actor, ActorType
from domain.authority import RoleAssignment, RoleDefinition
from domain.organization import Organization
from infrastructure.persistence.uow import UnitOfWork
from runtime.core import DORRuntime
from runtime.onboarding_runtime import ONBOARDING_INTENT_DECLARE_ACTION


def _runtime(tmp_path, *, grant: bool) -> DORRuntime:
    runtime = DORRuntime(f"sqlite:///{tmp_path / 'api-onboarding.db'}")
    runtime.boot()
    runtime.create_organization(Organization(id="org-a", name="Org A"))
    runtime.register_actor(
        Actor(id="alice", type=ActorType.HUMAN, identity="Alice"),
        "org-a",
    )
    if grant:
        role = RoleDefinition(
            id="role:onboarding-operator",
            name="Onboarding Operator",
            organization_id="org-a",
            capabilities=frozenset({ONBOARDING_INTENT_DECLARE_ACTION}),
        )
        assignment = RoleAssignment(
            actor_id="alice",
            organization_id="org-a",
            role_definition_id=role.id,
            created_at=datetime.now(timezone.utc),
        )
        with runtime.database.session("org-a") as session:
            with UnitOfWork(session) as uow:
                uow.authority.add_role_definition(role)
                uow.authority.assign_role(assignment)
    return runtime


def _request(command_id: str = "cmd-1") -> OnboardingIntentDeclareRequest:
    return OnboardingIntentDeclareRequest(
        command_id=command_id,
        source_repository="repository:external/example",
        purpose="extend",
        rationale="Extend the existing repository without replacing its stack.",
    )


def test_http_contract_forbids_client_owned_identity_and_tenant_fields() -> None:
    payload = {
        "command_id": "cmd-1",
        "source_repository": "repository:external/example",
        "purpose": "extend",
        "rationale": "Extend it.",
        "organization_id": "attacker-org",
        "declared_by": "mallory",
        "declared_at": "2026-09-05T12:00:00Z",
    }
    with pytest.raises(ValidationError) as exc_info:
        OnboardingIntentDeclareRequest.model_validate(payload)
    errors = exc_info.value.errors()
    assert {error["loc"][0] for error in errors} >= {
        "organization_id",
        "declared_by",
        "declared_at",
    }


def test_declaration_derives_actor_and_organization_from_authenticated_user(tmp_path) -> None:
    runtime = _runtime(tmp_path, grant=True)
    user = User(username="alice", organization_id="org-a")

    first = declare_onboarding_intent(_request(), current_user=user, dor=runtime)
    replay = declare_onboarding_intent(_request(), current_user=user, dor=runtime)

    assert first.replayed is False
    assert replay.replayed is True
    assert replay.intent.intent_id == first.intent.intent_id
    assert first.intent.organization_id == "org-a"
    assert first.intent.declared_by == "alice"
    assert first.intent.source_repository == "repository:external/example"


def test_declaration_fails_closed_without_external_capability(tmp_path) -> None:
    runtime = _runtime(tmp_path, grant=False)
    user = User(username="alice", organization_id="org-a")

    with pytest.raises(HTTPException) as exc_info:
        declare_onboarding_intent(_request(), current_user=user, dor=runtime)

    assert exc_info.value.status_code == 403
    assert exc_info.value.detail["error"] == "authorization_denied"
    assert exc_info.value.detail["capability_id"] == ONBOARDING_INTENT_DECLARE_ACTION


def test_rewrite_without_target_stack_is_rejected_at_domain_boundary(tmp_path) -> None:
    runtime = _runtime(tmp_path, grant=True)
    user = User(username="alice", organization_id="org-a")
    request = OnboardingIntentDeclareRequest(
        command_id="rewrite",
        source_repository="repository:external/rewrite",
        purpose="modernize_rewrite",
        rationale="Preserve behavior on a new stack.",
    )

    with pytest.raises(HTTPException) as exc_info:
        declare_onboarding_intent(request, current_user=user, dor=runtime)

    assert exc_info.value.status_code == 422
    assert exc_info.value.detail["error"] == "invalid_onboarding_intent"
