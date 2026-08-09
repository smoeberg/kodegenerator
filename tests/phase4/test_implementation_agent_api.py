"""API boundary tests for the operational Implementation Agent command."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import HTTPException

from api.auth import User
from api.endpoints.implementation_agent import propose_patch
from api.models import ImplementationProposalRequest
from domain.actor import Actor, ActorType
from domain.authority import RoleAssignment, RoleDefinition
from domain.organization import Organization
from domain.principal import Principal
from infrastructure.persistence.uow import UnitOfWork
from phase4.implementation_agent import (
    IMPLEMENTATION_ACTION,
    ImplementationAgentRuntime,
    ImplementationRequest,
    PatchCandidate,
)
from runtime.core import DORRuntime

RESOURCE = "repository:smoeberg/kodegenerator"
VALID_DIFF = """diff --git a/src/app.py b/src/app.py
--- a/src/app.py
+++ b/src/app.py
@@ -1 +1 @@
-VALUE = 1
+VALUE = 2
"""


class StaticImplementationProvider:
    provider_id = "fake.api"

    def __init__(self) -> None:
        self.calls: list[str] = []

    def propose_patch(self, request: ImplementationRequest) -> PatchCandidate:
        self.calls.append(request.request_fingerprint)
        return PatchCandidate(VALID_DIFF)


def _dor(tmp_path: Path) -> DORRuntime:
    runtime = DORRuntime(f"sqlite:///{tmp_path / 'implementation-api.db'}")
    runtime.boot()
    runtime.create_organization(Organization(id="org-a", name="org-a"))
    runtime.register_actor(
        Actor(id="actor-a", type=ActorType.HUMAN, identity="actor-a"),
        "org-a",
    )
    return runtime


def _grant(runtime: DORRuntime) -> None:
    with runtime.database.session() as session:
        with UnitOfWork(session) as uow:
            uow.authority.add_role_definition(
                RoleDefinition(
                    id="implementation.operator",
                    name="Implementation Operator",
                    organization_id="org-a",
                    capabilities=frozenset({IMPLEMENTATION_ACTION}),
                )
            )
            uow.authority.assign_role(
                RoleAssignment(
                    actor_id="actor-a",
                    organization_id="org-a",
                    role_definition_id="implementation.operator",
                )
            )


def _request(**overrides) -> ImplementationProposalRequest:
    values = {
        "organization_id": "org-a",
        "command_id": "api-implementation-1",
        "resource": RESOURCE,
        "instruction": "Set VALUE to 2.",
        "allowed_paths": ["src/app.py"],
        "max_files": 1,
        "max_changed_lines": 2,
        "context_items": [
            {
                "source": "repository",
                "key": "src/app.py",
                "value": "VALUE = 1\n",
                "provenance": "git:abc123:src/app.py",
            }
        ],
    }
    values.update(overrides)
    return ImplementationProposalRequest(**values)


def _user() -> User:
    return User(username="actor-a", full_name="actor-a")


def _implementation_runtime(provider) -> ImplementationAgentRuntime:
    return ImplementationAgentRuntime(
        provider=provider,
        allowed_resources=(RESOURCE,),
    )


def test_authorized_api_command_returns_governed_proposal_and_replay(tmp_path):
    dor = _dor(tmp_path)
    _grant(dor)
    provider = StaticImplementationProvider()
    implementation_runtime = _implementation_runtime(provider)

    first = propose_patch(_request(), _user(), dor, implementation_runtime)
    second = propose_patch(_request(), _user(), dor, implementation_runtime)

    assert first.authority_decision == "allow"
    assert first.execution_status == "succeeded"
    assert first.outcome_status == "succeeded"
    assert first.proposal.unified_diff == VALID_DIFF
    assert second.execution_status == "replayed"
    assert second.replayed is True
    assert second.proposal.proposal_id == first.proposal.proposal_id
    assert len(provider.calls) == 1

    context = dor.establish_context(
        Principal(id="actor-a", type="user"), "org-a", "actor-a"
    )
    events = dor.get_events(
        context,
        "org-a",
        include_authorization_audit=True,
    )
    granted = [event for event in events if event.metadata.get("allowed") is True]
    assert len(granted) == 2
    assert granted[0].metadata["capability_id"] == IMPLEMENTATION_ACTION


def test_api_denies_human_without_capability_before_agent_runtime(tmp_path):
    dor = _dor(tmp_path)
    provider = StaticImplementationProvider()

    with pytest.raises(HTTPException) as exc:
        propose_patch(
            _request(),
            _user(),
            dor,
            _implementation_runtime(provider),
        )

    assert exc.value.status_code == 403
    assert exc.value.detail["error"] == "authorization_denied"
    assert provider.calls == []


def test_api_denies_repository_outside_agent_policy(tmp_path):
    dor = _dor(tmp_path)
    _grant(dor)
    provider = StaticImplementationProvider()

    with pytest.raises(HTTPException) as exc:
        propose_patch(
            _request(resource="repository:other/project"),
            _user(),
            dor,
            _implementation_runtime(provider),
        )

    assert exc.value.status_code == 403
    assert exc.value.detail["error"] == "agent_authority_denied"
    assert provider.calls == []


def test_api_rejects_command_id_rebinding(tmp_path):
    dor = _dor(tmp_path)
    _grant(dor)
    provider = StaticImplementationProvider()
    implementation_runtime = _implementation_runtime(provider)
    propose_patch(_request(), _user(), dor, implementation_runtime)

    with pytest.raises(HTTPException) as exc:
        propose_patch(
            _request(instruction="Set VALUE to 3."),
            _user(),
            dor,
            implementation_runtime,
        )

    assert exc.value.status_code == 409
    assert exc.value.detail["error"] == "implementation_command_conflict"
    assert len(provider.calls) == 1
