"""Adversarial tests for governed patch application and trusted tool evidence."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest
from fastapi import HTTPException

import phase4.implementation_agent.patch_adapter as patch_adapter_module
from api.auth import User
from api.dependencies import (
    ImplementationAgentConfigurationError,
    get_governed_patch_runtime,
    get_implementation_agent_runtime,
)
from api.endpoints.implementation_agent import execute_patch
from api.main import app
from api.models import (
    ImplementationPatchExecutionRequest,
    ImplementationPatchExecutionResponse,
)
from domain.actor import Actor, ActorType
from domain.authority import RoleAssignment, RoleDefinition
from domain.organization import Organization
from infrastructure.persistence.uow import UnitOfWork
from phase4.context_packet import ContextItem
from phase4.execution import ExecutionStatus
from phase4.implementation_agent import (
    IMPLEMENTATION_APPLY_ACTION,
    ChangeBudget,
    GovernedPatchCommandConflictError,
    GovernedPatchExecutionRuntime,
    ImplementationAgentRuntime,
    ImplementationRequest,
    PatchCandidate,
    PatchExecutionContractError,
    PatchExecutionRequest,
    PatchRecordStatus,
    PatchWorkspaceError,
    RawToolResult,
    SubprocessToolRunner,
    ToolKind,
    ToolStatus,
    TrustedToolSpec,
    WorkspacePatchExecutor,
    canonical_python_tools,
)
from phase4.outcome.models import OutcomeStatus
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
    provider_id = "fake.patch-execution"

    def __init__(self, diffs: tuple[str, ...] = (VALID_DIFF,)) -> None:
        self._diffs = list(diffs)
        self.calls: list[str] = []

    def propose_patch(self, request: ImplementationRequest) -> PatchCandidate:
        self.calls.append(request.request_fingerprint)
        if not self._diffs:
            raise AssertionError("no deterministic diff remains")
        return PatchCandidate(self._diffs.pop(0))


class RecordingToolRunner:
    def __init__(
        self,
        *,
        outcomes: dict[str, RawToolResult] | None = None,
        mutate_touched_path: bool = False,
    ) -> None:
        self.outcomes = outcomes or {}
        self.mutate_touched_path = mutate_touched_path
        self.calls: list[tuple[str, Path]] = []
        self.secret_files_seen: list[bool] = []

    def run(self, tool: TrustedToolSpec, *, cwd: Path) -> RawToolResult:
        self.calls.append((tool.tool_id, cwd))
        self.secret_files_seen.append((cwd / ".env").exists())
        if self.mutate_touched_path and len(self.calls) == 1:
            (cwd / "src" / "app.py").write_text("VALUE = 99\n", encoding="utf-8")
        return self.outcomes.get(
            tool.tool_id,
            RawToolResult(
                ToolStatus.PASSED,
                0,
                f"{tool.tool_id} ok\n".encode(),
                b"",
            ),
        )


def _tools() -> tuple[TrustedToolSpec, ...]:
    executable = str(Path(sys.executable).resolve())
    return (
        TrustedToolSpec(
            "test.lint",
            ToolKind.LINT,
            (executable, "-c", "print('lint')"),
        ),
        TrustedToolSpec(
            "test.test",
            ToolKind.TEST,
            (executable, "-c", "print('test')"),
        ),
        TrustedToolSpec(
            "test.build",
            ToolKind.BUILD,
            (executable, "-c", "print('build')"),
        ),
    )


def _proposal_runtime(
    root: Path,
    *,
    provider: StaticProvider | None = None,
    diff: str = VALID_DIFF,
    allowed_paths: tuple[str, ...] = ("src/app.py",),
):
    selected = provider or StaticProvider((diff,))
    runtime = ImplementationAgentRuntime(
        provider=selected,
        allowed_resources=(RESOURCE,),
    )
    run = runtime.run(
        resource=RESOURCE,
        instruction="Apply the bounded change.",
        allowed_paths=allowed_paths,
        context_items=(
            ContextItem(
                source="requirements",
                key="acceptance",
                value="The bounded patch must pass all trusted tools.",
                provenance="requirement:PATCH-1",
            ),
        ),
        budget=ChangeBudget(
            max_files=len(allowed_paths),
            max_changed_lines=20,
        ),
        idempotency_key="proposal-command-" + str(len(selected.calls)),
    )
    return runtime, run.proposal, selected


def _workspace(tmp_path: Path) -> Path:
    root = tmp_path / "workspace"
    (root / "src").mkdir(parents=True)
    (root / "src" / "app.py").write_text("VALUE = 1\n", encoding="utf-8")
    (root / ".env").write_text("SECRET=must-not-enter-tool-copy\n", encoding="utf-8")
    return root


def _patch_runtime(
    root: Path,
    proposal_runtime: ImplementationAgentRuntime,
    runner: RecordingToolRunner,
) -> GovernedPatchExecutionRuntime:
    return GovernedPatchExecutionRuntime(
        proposal_runtime=proposal_runtime,
        workspace_root=root,
        tools=_tools(),
        tool_runner=runner,
    )


def test_successful_patch_is_authorized_evidenced_committed_and_replayed(tmp_path):
    root = _workspace(tmp_path)
    proposal_runtime, proposal, _ = _proposal_runtime(root)
    runner = RecordingToolRunner()
    runtime = _patch_runtime(root, proposal_runtime, runner)

    first = runtime.run(proposal_id=proposal.proposal_id, idempotency_key="apply-1")
    second = runtime.run(proposal_id=proposal.proposal_id, idempotency_key="apply-1")

    assert (root / "src" / "app.py").read_text(encoding="utf-8") == "VALUE = 2\n"
    assert first.authority.action == IMPLEMENTATION_APPLY_ACTION
    assert first.execution.status is ExecutionStatus.SUCCEEDED
    assert first.outcome.status is OutcomeStatus.SUCCEEDED
    assert first.record.status is PatchRecordStatus.SUCCEEDED
    assert first.record.committed is True
    assert first.record.rolled_back is False
    assert first.record.artifact is not None
    assert len(first.record.evidence) == 3
    assert {item.kind for item in first.record.evidence} == {
        ToolKind.LINT,
        ToolKind.TEST,
        ToolKind.BUILD,
    }
    assert all(
        item.artifact_id == first.record.artifact.artifact_id
        for item in first.record.evidence
    )
    assert all(not seen for seen in runner.secret_files_seen)
    assert second.replayed is True
    assert second.execution.status is ExecutionStatus.REPLAYED
    assert second.record.record_id == first.record.record_id
    assert [item[0] for item in runner.calls] == [
        "test.lint",
        "test.test",
        "test.build",
    ]
    capabilities = {item.name for item in proposal_runtime.agent.capabilities}
    assert IMPLEMENTATION_APPLY_ACTION in capabilities


def test_canonical_python_toolchain_runs_in_validation_workspace(tmp_path):
    root = _workspace(tmp_path)
    (root / "src" / "__init__.py").write_text("", encoding="utf-8")
    (root / "test_app.py").write_text(
        "from src.app import VALUE\n\n\ndef test_value():\n    assert VALUE == 2\n",
        encoding="utf-8",
    )
    proposal_runtime, proposal, _ = _proposal_runtime(root)
    runtime = GovernedPatchExecutionRuntime(
        proposal_runtime=proposal_runtime,
        workspace_root=root,
        tools=canonical_python_tools(timeout_seconds=30, max_output_bytes=64 * 1024),
    )

    run = runtime.run(proposal_id=proposal.proposal_id, idempotency_key="real-tools")

    assert run.record.status is PatchRecordStatus.SUCCEEDED
    assert [item.status for item in run.record.evidence] == [
        ToolStatus.PASSED,
        ToolStatus.PASSED,
        ToolStatus.PASSED,
    ]
    assert (root / "src" / "app.py").read_text(encoding="utf-8") == "VALUE = 2\n"


def test_failed_trusted_tool_leaves_live_workspace_unchanged(tmp_path):
    root = _workspace(tmp_path)
    proposal_runtime, proposal, _ = _proposal_runtime(root)
    runner = RecordingToolRunner(
        outcomes={
            "test.test": RawToolResult(
                ToolStatus.FAILED,
                7,
                b"",
                b"assertion failed\n",
            )
        }
    )
    runtime = _patch_runtime(root, proposal_runtime, runner)

    run = runtime.run(proposal_id=proposal.proposal_id, idempotency_key="apply-fail")

    assert (root / "src" / "app.py").read_text(encoding="utf-8") == "VALUE = 1\n"
    assert run.execution.status is ExecutionStatus.FAILED
    assert run.outcome.status is OutcomeStatus.FAILED
    assert run.record.status is PatchRecordStatus.FAILED
    assert run.record.committed is False
    assert run.record.rolled_back is True
    assert [item.status for item in run.record.evidence] == [
        ToolStatus.PASSED,
        ToolStatus.FAILED,
    ]
    assert run.record.evidence[-1].stderr.content == "assertion failed\n"


def test_tool_cannot_modify_approved_patch_output(tmp_path):
    root = _workspace(tmp_path)
    proposal_runtime, proposal, _ = _proposal_runtime(root)
    runner = RecordingToolRunner(mutate_touched_path=True)
    runtime = _patch_runtime(root, proposal_runtime, runner)

    run = runtime.run(proposal_id=proposal.proposal_id, idempotency_key="apply-mutate")

    assert run.record.status is PatchRecordStatus.FAILED
    assert "modified" in (run.record.error or "")
    assert (root / "src" / "app.py").read_text(encoding="utf-8") == "VALUE = 1\n"


def test_baseline_drift_fails_before_any_tool_runs(tmp_path):
    root = _workspace(tmp_path)
    _, proposal, _ = _proposal_runtime(root)
    runner = RecordingToolRunner()
    workspace = WorkspacePatchExecutor(root, tool_runner=runner)
    request = PatchExecutionRequest(proposal, workspace.observe(proposal), _tools())
    (root / "src" / "app.py").write_text("VALUE = 8\n", encoding="utf-8")

    record = workspace.execute(request)

    assert record.status is PatchRecordStatus.FAILED
    assert "baseline" in (record.error or "")
    assert runner.calls == []
    assert (root / "src" / "app.py").read_text(encoding="utf-8") == "VALUE = 8\n"


def test_toolchain_cannot_omit_a_required_evidence_class(tmp_path):
    root = _workspace(tmp_path)
    _, proposal, _ = _proposal_runtime(root)
    workspace = WorkspacePatchExecutor(root)

    with pytest.raises(PatchExecutionContractError, match="lint, test, and build"):
        PatchExecutionRequest(proposal, workspace.observe(proposal), _tools()[:2])


def test_touched_symlink_and_hardlink_fail_closed(tmp_path):
    root = _workspace(tmp_path)
    _, proposal, _ = _proposal_runtime(root)
    target = root / "src" / "app.py"
    original = root / "src" / "original.py"
    target.rename(original)
    target.symlink_to(original)

    with pytest.raises(PatchWorkspaceError, match="symlink"):
        WorkspacePatchExecutor(root).observe(proposal)

    target.unlink()
    os.link(original, target)
    with pytest.raises(PatchWorkspaceError, match="hard links"):
        WorkspacePatchExecutor(root).observe(proposal)


def test_unrelated_workspace_symlink_is_not_copied_or_followed(tmp_path):
    root = _workspace(tmp_path)
    proposal_runtime, proposal, _ = _proposal_runtime(root)
    outside = tmp_path / "outside"
    outside.mkdir()
    (root / "linked-outside").symlink_to(outside, target_is_directory=True)
    runner = RecordingToolRunner()
    runtime = _patch_runtime(root, proposal_runtime, runner)

    run = runtime.run(proposal_id=proposal.proposal_id, idempotency_key="apply-link")

    assert run.record.status is PatchRecordStatus.FAILED
    assert "symlink" in (run.record.error or "")
    assert runner.calls == []
    assert (root / "src" / "app.py").read_text(encoding="utf-8") == "VALUE = 1\n"


def test_create_and_delete_are_committed_only_after_tools_pass(tmp_path):
    root = _workspace(tmp_path)
    (root / "src" / "old.py").write_text("OLD = 1\n", encoding="utf-8")
    diff = """diff --git a/src/new.py b/src/new.py
new file mode 100644
--- /dev/null
+++ b/src/new.py
@@ -0,0 +1 @@
+NEW = 1
diff --git a/src/old.py b/src/old.py
deleted file mode 100644
--- a/src/old.py
+++ /dev/null
@@ -1 +0,0 @@
-OLD = 1
"""
    proposal_runtime, proposal, _ = _proposal_runtime(
        root,
        diff=diff,
        allowed_paths=("src/new.py", "src/old.py"),
    )
    runtime = _patch_runtime(root, proposal_runtime, RecordingToolRunner())

    run = runtime.run(proposal_id=proposal.proposal_id, idempotency_key="create-delete")

    assert run.record.status is PatchRecordStatus.SUCCEEDED
    assert (root / "src" / "new.py").read_text(encoding="utf-8") == "NEW = 1\n"
    assert not (root / "src" / "old.py").exists()


def test_multi_file_commit_failure_restores_every_live_path(tmp_path, monkeypatch):
    root = _workspace(tmp_path)
    (root / "src" / "other.py").write_text("OTHER = 1\n", encoding="utf-8")
    second = """diff --git a/src/other.py b/src/other.py
--- a/src/other.py
+++ b/src/other.py
@@ -1 +1 @@
-OTHER = 1
+OTHER = 2
"""
    proposal_runtime, proposal, _ = _proposal_runtime(
        root,
        diff=VALID_DIFF + second,
        allowed_paths=("src/app.py", "src/other.py"),
    )
    runner = RecordingToolRunner()
    runtime = _patch_runtime(root, proposal_runtime, runner)
    real_replace = os.replace
    live_commits = 0

    def fail_second_live_commit(source, destination, *args, **kwargs):
        nonlocal live_commits
        if ".dor-patch-" in str(source):
            live_commits += 1
            if live_commits == 2:
                raise OSError("injected second-file commit failure")
        return real_replace(source, destination, *args, **kwargs)

    monkeypatch.setattr(patch_adapter_module.os, "replace", fail_second_live_commit)
    run = runtime.run(proposal_id=proposal.proposal_id, idempotency_key="rollback")

    assert run.record.status is PatchRecordStatus.FAILED
    assert "rolled back" in (run.record.error or "")
    assert (root / "src" / "app.py").read_text(encoding="utf-8") == "VALUE = 1\n"
    assert (root / "src" / "other.py").read_text(encoding="utf-8") == "OTHER = 1\n"


def test_command_id_cannot_be_rebound_to_another_proposal(tmp_path):
    root = _workspace(tmp_path)
    second_diff = VALID_DIFF.replace("VALUE = 2", "VALUE = 3")
    provider = StaticProvider((VALID_DIFF, second_diff))
    proposal_runtime, first, _ = _proposal_runtime(root, provider=provider)
    second_run = proposal_runtime.run(
        resource=RESOURCE,
        instruction="Apply another bounded change.",
        allowed_paths=("src/app.py",),
        context_items=(ContextItem("requirements", "second", "VALUE becomes 3"),),
        budget=ChangeBudget(max_files=1, max_changed_lines=2),
        idempotency_key="proposal-command-2",
    )
    runtime = _patch_runtime(root, proposal_runtime, RecordingToolRunner())
    runtime.run(proposal_id=first.proposal_id, idempotency_key="same-command")

    with pytest.raises(GovernedPatchCommandConflictError):
        runtime.run(
            proposal_id=second_run.proposal.proposal_id,
            idempotency_key="same-command",
        )


def test_subprocess_runner_enforces_output_limit_and_timeout(tmp_path, monkeypatch):
    executable = str(Path(sys.executable).resolve())
    output_tool = TrustedToolSpec(
        "output",
        ToolKind.LINT,
        (executable, "-c", "print('too much output')"),
        max_output_bytes=2,
    )
    runner = SubprocessToolRunner()

    output = runner.run(output_tool, cwd=tmp_path)
    assert output.status is ToolStatus.OUTPUT_LIMIT

    def timeout(*_args, **kwargs):
        raise subprocess.TimeoutExpired(cmd=output_tool.command, timeout=1, output=b"x")

    monkeypatch.setattr(patch_adapter_module.subprocess, "run", timeout)
    timed_out = runner.run(output_tool, cwd=tmp_path)
    assert timed_out.status is ToolStatus.TIMED_OUT
    assert timed_out.stdout == b"x"


def test_subprocess_runner_rejects_executable_tampering(tmp_path):
    executable = tmp_path / "trusted-tool"
    executable.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    executable.chmod(0o755)
    tool = TrustedToolSpec(
        "tamper",
        ToolKind.LINT,
        (str(executable),),
    )
    executable.write_text("#!/bin/sh\nexit 7\n", encoding="utf-8")

    result = SubprocessToolRunner().run(tool, cwd=tmp_path)

    assert result.status is ToolStatus.START_ERROR
    assert b"fingerprint" in result.stderr


def _dor(tmp_path: Path) -> DORRuntime:
    runtime = DORRuntime(f"sqlite:///{tmp_path / 'patch-api.db'}")
    runtime.boot()
    runtime.create_organization(Organization(id="org-a", name="org-a"))
    runtime.register_actor(
        Actor(id="actor-a", type=ActorType.HUMAN, identity="actor-a"),
        "org-a",
    )
    return runtime


def _grant_apply(runtime: DORRuntime) -> None:
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


def test_api_exposes_proposal_identity_but_no_command_or_tool_selection(tmp_path):
    root = _workspace(tmp_path)
    proposal_runtime, proposal, _ = _proposal_runtime(root)
    runner = RecordingToolRunner()
    patch_runtime = _patch_runtime(root, proposal_runtime, runner)
    dor = _dor(tmp_path)
    _grant_apply(dor)
    request = ImplementationPatchExecutionRequest(
        organization_id="org-a",
        command_id="api-apply-1",
        proposal_id=proposal.proposal_id,
    )

    response = execute_patch(
        request,
        User(username="actor-a", full_name="actor-a"),
        dor,
        patch_runtime,
    )

    assert isinstance(response, ImplementationPatchExecutionResponse)
    assert response.committed is True
    assert response.record_status == "succeeded"
    assert response.artifact is not None
    assert len(response.evidence) == 3
    fields = set(ImplementationPatchExecutionRequest.model_fields)
    assert fields == {"organization_id", "command_id", "proposal_id"}
    assert "/implementation-agent/executions" in app.openapi()["paths"]


def test_api_denies_human_before_patch_runtime_executes(tmp_path):
    root = _workspace(tmp_path)
    proposal_runtime, proposal, _ = _proposal_runtime(root)
    runner = RecordingToolRunner()
    patch_runtime = _patch_runtime(root, proposal_runtime, runner)
    dor = _dor(tmp_path)

    with pytest.raises(HTTPException) as exc:
        execute_patch(
            ImplementationPatchExecutionRequest(
                organization_id="org-a",
                command_id="api-denied",
                proposal_id=proposal.proposal_id,
            ),
            User(username="actor-a", full_name="actor-a"),
            dor,
            patch_runtime,
        )

    assert exc.value.status_code == 403
    assert runner.calls == []
    assert (root / "src" / "app.py").read_text(encoding="utf-8") == "VALUE = 1\n"


def _clear_runtime_caches() -> None:
    get_governed_patch_runtime.cache_clear()
    get_implementation_agent_runtime.cache_clear()


def test_patch_dependency_is_fail_closed_without_workspace_or_tools(monkeypatch):
    _clear_runtime_caches()
    monkeypatch.delenv("DOR_PATCH_WORKSPACE_ROOT", raising=False)
    monkeypatch.delenv("DOR_PATCH_ALLOWED_TOOLS", raising=False)

    with pytest.raises(ImplementationAgentConfigurationError, match="WORKSPACE_ROOT"):
        get_governed_patch_runtime()

    _clear_runtime_caches()


def test_patch_dependency_accepts_only_the_static_complete_toolchain(
    tmp_path, monkeypatch
):
    root = _workspace(tmp_path)
    _clear_runtime_caches()
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("DOR_IMPLEMENTATION_MODEL", "test-model")
    monkeypatch.setenv("DOR_IMPLEMENTATION_ALLOWED_RESOURCES", RESOURCE)
    monkeypatch.setenv("DOR_PATCH_WORKSPACE_ROOT", str(root))
    monkeypatch.setenv(
        "DOR_PATCH_ALLOWED_TOOLS",
        "python.ruff,python.pytest,python.compileall",
    )
    try:
        runtime = get_governed_patch_runtime()
        assert tuple(tool.tool_id for tool in runtime.tools) == (
            "python.ruff",
            "python.pytest",
            "python.compileall",
        )
        assert all(Path(tool.command[0]).is_absolute() for tool in runtime.tools)
        assert all(
            dict(tool.environment)["DOR_JWT_SECRET_KEY"] != "test-key"
            for tool in runtime.tools
        )
    finally:
        _clear_runtime_caches()


def test_patch_dependency_rejects_unknown_tool_id(tmp_path, monkeypatch):
    root = _workspace(tmp_path)
    _clear_runtime_caches()
    monkeypatch.setenv("DOR_PATCH_WORKSPACE_ROOT", str(root))
    monkeypatch.setenv(
        "DOR_PATCH_ALLOWED_TOOLS",
        "python.ruff,caller.shell,python.compileall",
    )
    try:
        with pytest.raises(ImplementationAgentConfigurationError, match="unknown"):
            get_governed_patch_runtime()
    finally:
        _clear_runtime_caches()
