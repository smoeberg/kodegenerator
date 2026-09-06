"""Tenant-binding regressions for the governed patch execution boundary."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest
from fastapi import HTTPException

from api.auth import User
from api.endpoints.implementation_agent import execute_patch
from api.models import ImplementationPatchExecutionRequest
from domain.actor import Actor, ActorType
from domain.authority import RoleAssignment, RoleDefinition
from domain.organization import Organization
from infrastructure.persistence.uow import UnitOfWork
from phase4.context_packet import ContextItem
from phase4.implementation_agent import (
    IMPLEMENTATION_APPLY_ACTION,
    ChangeBudget,
    GovernedPatchExecutionRuntime,
    GovernedPatchRuntimeError,
    ImplementationAgentRuntime,
    ImplementationRequest,
    PatchCandidate,
    RawToolResult,
    ToolKind,
    ToolStatus,
    TrustedToolSpec,
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


class StaticProvider:
    provider_id = "fake.tenant-binding"

    def propose_patch(self, _request: ImplementationRequest) -> PatchCandidate:
        return PatchCandidate(VALID_DIFF)


class NeverRunTools:
    def __init__(self) -> None:
        self.calls = 0

    def run(self, _tool: TrustedToolSpec, *, cwd: Path) -> RawToolResult:
        self.calls += 1
        raise AssertionError(f"tool must not run for tenant mismatch: {cwd}")


def _tools() -> tuple[TrustedToolSpec, ...]:
    executable = str(Path(sys.executable).resolve())
    return tuple(
        TrustedToolSpec(
            f"test.{kind.value}",
            kind,
            (executable, "-c", "print('ok')"),
        )
        for kind in (ToolKind.LINT, ToolKind.TEST, ToolKind.BUILD)
    )


def test_patch_runtime_rejects_expected_organization_mismatch_before_tools(tmp_path) -> None:
    workspace = tmp_path / "workspace"
    (workspace / "src").mkdir(parents=True)
    (workspace / "src" / "app.py").write_text("VALUE = 1\n", encoding="utf-8")
    proposal_runtime = ImplementationAgentRuntime(
        provider=StaticProvider(),
        allowed_resources=(RESOURCE,),
    )
    proposal = proposal_runtime.run(
        organization_id="org-b",
        resource=RESOURCE,
        instruction="Set VALUE to 2.",
        allowed_paths=("src/app.py",),
        context_items=(ContextItem("requirements", "goal", "VALUE becomes 2"),),
        budget=ChangeBudget(max_files=1, max_changed_lines=2),
        idempotency_key="proposal-org-b",
    ).proposal
    runner = NeverRunTools()
    runtime = GovernedPatchExecutionRuntime(
        proposal_runtime=proposal_runtime,
        workspace_root=workspace,
        tools=_tools(),
        tool_runner=runner,
    )

    with pytest.raises(GovernedPatchRuntimeError, match="organization"):
        runtime.run(
            proposal_id=proposal.proposal_id,
            idempotency_key="apply-org-a",
            organization_id="org-a",
        )

    assert runner.calls == 0
    assert (workspace / "src" / "app.py").read_text(encoding="utf-8") == "VALUE = 1\n"


def _dor(tmp_path: Path) -> DORRuntime:
    runtime = DORRuntime(f"sqlite:///{tmp_path / 'tenant-api.db'}")
    runtime.boot()
    runtime.create_organization(Organization(id="org-a", name="org-a"))
    runtime.register_actor(
        Actor(id="actor-a", type=ActorType.HUMAN, identity="actor-a"),
        "org-a",
    )
    with runtime.database.session() as session, UnitOfWork(session) as uow:
        uow.authority.add_role_definition(
            RoleDefinition(
                id="implementation.patch-operator",
                name="Patch Operator",
                organization_id="org-a",
                capabilities=frozenset({IMPLEMENTATION_APPLY_ACTION}),
            )
        )
        uow.authority.assign_role(
            RoleAssignment(
                actor_id="actor-a",
                organization_id="org-a",
                role_definition_id="implementation.patch-operator",
            )
        )
    return runtime


def test_patch_api_passes_authenticated_request_tenant_into_runtime(tmp_path) -> None:
    class RecordingRuntime:
        def __init__(self) -> None:
            self.kwargs = None

        def run(self, **kwargs):
            self.kwargs = kwargs
            raise GovernedPatchRuntimeError("stop after tenant assertion")

    runtime = RecordingRuntime()
    request = ImplementationPatchExecutionRequest(
        organization_id="org-a",
        command_id="apply-command-tenant",
        proposal_id="a" * 64,
    )

    with pytest.raises(HTTPException) as exc:
        execute_patch(
            request,
            User(username="actor-a", full_name="actor-a"),
            _dor(tmp_path),
            runtime,
        )

    assert exc.value.status_code == 422
    assert runtime.kwargs == {
        "proposal_id": "a" * 64,
        "idempotency_key": "apply-command-tenant",
        "organization_id": "org-a",
    }
