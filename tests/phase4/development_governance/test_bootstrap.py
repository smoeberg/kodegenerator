from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from phase4.development_governance.__main__ import production_registry
from phase4.development_governance.bootstrap import (
    ROLE_NAMES,
    GovernanceAuditLog,
    GovernanceBootstrap,
    GovernanceBootstrapConfig,
    GovernanceBootstrapError,
    GovernanceProviderRegistry,
    RoleBinding,
    config_from_dict,
    governed_llm_factory,
)
from phase4.development_governance.contracts import (
    ArtifactSubmission,
    ProblemApproval,
    ProblemBrief,
    ProblemDecision,
    ScopeConformance,
    SolutionApproval,
    SolutionDecision,
    SolutionProposal,
)
from phase4.development_governance.providers import (
    GovernedCoderProvider,
    GovernedImplementationLifecycleExecutor,
)
from phase4.implementation_agent import (
    GovernedPatchExecutionRuntime,
    ImplementationAgentRuntime,
    PatchCandidate,
    RawToolResult,
    ToolKind,
    ToolStatus,
    TrustedToolSpec,
)


def bindings(**overrides: str) -> dict[str, RoleBinding]:
    return {
        role: RoleBinding(overrides.get(role, f"logical.{role}"), "test", "model", "v1", "0" * 64)
        for role in ROLE_NAMES
    }


def make_problem() -> ProblemBrief:
    return ProblemBrief("p", 1, "title", "problem", "impact", proposed_scope=("scope",))


def test_config_requires_exact_five_pairwise_distinct_logical_roles(tmp_path: Path) -> None:
    valid = bindings()
    config = GovernanceBootstrapConfig("org", tmp_path, valid, "a" * 40)
    assert tuple(config.roles) == ROLE_NAMES

    missing = dict(valid)
    missing.pop("auditor")
    with pytest.raises(GovernanceBootstrapError, match="missing"):
        GovernanceBootstrapConfig("org", tmp_path, missing, "a" * 40)

    with pytest.raises(GovernanceBootstrapError, match="pairwise distinct"):
        GovernanceBootstrapConfig("org", tmp_path, bindings(reviewer="logical.coder"), "a" * 40)


def test_registry_is_fail_closed_for_unknown_factory_and_identity_mismatch() -> None:
    registry = GovernanceProviderRegistry({"test": lambda role, binding, org: type("P", (), {"provider_id": "wrong"})()})
    with pytest.raises(GovernanceBootstrapError, match="identity mismatch"):
        registry.build("coder", RoleBinding("coder", "test", "model", "v1", "0" * 64), "org")
    with pytest.raises(GovernanceBootstrapError, match="unknown provider factory"):
        registry.build("coder", RoleBinding("coder", "missing", "model", "v1", "0" * 64), "org")


def test_governed_llm_factory_has_no_coder_fallback() -> None:
    runtime_calls: list[str] = []
    factory = governed_llm_factory(lambda binding: runtime_calls.append(binding.provider_id))
    with pytest.raises(GovernanceBootstrapError, match="LLM fallback is prohibited"):
        factory("coder", RoleBinding("coder", "governed_llm", "model", "v1", "0" * 64), "org")
    assert runtime_calls == []


def test_config_parser_rejects_unknown_fields_before_provider_calls(tmp_path: Path) -> None:
    raw = {
        "organization_id": "org", "repository_root": str(tmp_path),
        "base_sha": "a" * 40,
        "roles": {role: {"provider_id": f"logical.{role}", "factory": "test", "model": "m", "prompt_version": "v1", "options_fingerprint": "0" * 64} for role in ROLE_NAMES},
        "implicit_execution_authority": True,
    }
    with pytest.raises(GovernanceBootstrapError, match="unknown bootstrap fields"):
        config_from_dict(raw)


def test_audit_record_is_canonical_process_local_json_and_optional_file(tmp_path: Path) -> None:
    path = tmp_path / "audit.json"
    audit = GovernanceAuditLog(path)
    audit.append("providers-bound", {"coder": "logical.coder", "reviewer": "logical.reviewer"})
    document = json.loads(audit.to_json())
    assert document["schema_version"] == "governance-bootstrap-audit-v1"
    assert document["records"][0]["event"] == "providers-bound"
    assert json.loads(path.read_text(encoding="utf-8")) == document


def test_route_fingerprint_binds_prompt_and_options() -> None:
    first = RoleBinding("po", "test", "model", "v1", "0" * 64)
    assert first.route_fingerprint == RoleBinding("po", "test", "model", "v1", "0" * 64).route_fingerprint
    assert first.route_fingerprint != RoleBinding("po", "test", "model", "v2", "0" * 64).route_fingerprint
    assert first.route_fingerprint != RoleBinding("po", "test", "model", "v1", "1" * 64).route_fingerprint


def test_wrong_or_dirty_base_fails_before_any_provider_factory_call(tmp_path: Path) -> None:
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@example.test"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=tmp_path, check=True)
    (tmp_path / "tracked").write_text("x")
    subprocess.run(["git", "add", "tracked"], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-m", "base"], cwd=tmp_path, check=True, capture_output=True)
    head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=tmp_path, check=True, capture_output=True, text=True).stdout.strip()
    calls: list[str] = []
    registry = GovernanceProviderRegistry({"test": lambda role, binding, org: calls.append(role)})
    wrong = GovernanceBootstrapConfig("org", tmp_path, bindings(), "0" * 40)
    with pytest.raises(GovernanceBootstrapError, match="does not equal"):
        GovernanceBootstrap(wrong, registry).coordinator()
    assert calls == []
    (tmp_path / "tracked").write_text("dirty")
    dirty = GovernanceBootstrapConfig("org", tmp_path, bindings(), head)
    with pytest.raises(GovernanceBootstrapError, match="clean"):
        GovernanceBootstrap(dirty, registry).coordinator()
    assert calls == []


def test_audit_path_inside_repository_is_rejected_before_write(tmp_path: Path) -> None:
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@example.test"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=tmp_path, check=True)
    (tmp_path / "tracked").write_text("x")
    subprocess.run(["git", "add", "tracked"], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-m", "base"], cwd=tmp_path, check=True, capture_output=True)
    head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=tmp_path, check=True, capture_output=True, text=True).stdout.strip()
    audit_path = tmp_path / "audit.json"
    config = GovernanceBootstrapConfig("org", tmp_path, bindings(), head, audit_path)
    with pytest.raises(GovernanceBootstrapError, match="outside"):
        GovernanceBootstrap(config, GovernanceProviderRegistry({"test": lambda *args: object()})).coordinator()
    assert not audit_path.exists()


def test_failure_audit_omits_secret_bearing_exception_message(tmp_path: Path, monkeypatch) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    subprocess.run(["git", "init"], cwd=root, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@example.test"], cwd=root, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=root, check=True)
    (root / "tracked").write_text("x")
    subprocess.run(["git", "add", "tracked"], cwd=root, check=True)
    subprocess.run(["git", "commit", "-m", "base"], cwd=root, check=True, capture_output=True)
    head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=root, check=True, capture_output=True, text=True).stdout.strip()
    audit_path = tmp_path / "audit.json"
    bootstrap = GovernanceBootstrap(
        GovernanceBootstrapConfig("org", root, bindings(), head, audit_path),
        GovernanceProviderRegistry({"test": lambda *args: object()}),
    )

    class Runner:
        def run_semantic(self, problem):
            raise RuntimeError("super-secret-token")

    monkeypatch.setattr(bootstrap, "_coordinator_after_preflight", lambda: Runner())
    with pytest.raises(RuntimeError, match="super-secret-token"):
        bootstrap.run(make_problem())
    document = audit_path.read_text(encoding="utf-8")
    assert "super-secret-token" not in document
    assert "message" not in json.loads(document)["records"][-1]["payload"]


def test_governed_coder_observes_commit_created_by_injected_executor(tmp_path: Path) -> None:
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@example.test"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=tmp_path, check=True)
    (tmp_path / "base").write_text("base")
    subprocess.run(["git", "add", "base"], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-m", "base"], cwd=tmp_path, check=True, capture_output=True)
    base = subprocess.run(["git", "rev-parse", "HEAD"], cwd=tmp_path, check=True, capture_output=True, text=True).stdout.strip()

    class Executor:
        receipt = None

        def execute(self, problem, solution, approval) -> None:
            (tmp_path / "change").write_text("change")
            subprocess.run(["git", "add", "change"], cwd=tmp_path, check=True)
            subprocess.run(["git", "commit", "-m", "artifact"], cwd=tmp_path, check=True, capture_output=True)
            artifact = subprocess.run(["git", "rev-parse", "HEAD"], cwd=tmp_path, check=True,
                                      capture_output=True, text=True).stdout.strip()
            self.receipt = ArtifactSubmission(artifact, base, ("change",))

    submission = GovernedCoderProvider("coder", Executor(), tmp_path, base).implement(None, None, None)  # type: ignore[arg-type]
    assert submission.base_version == base
    assert submission.changed_files == ("change",)
    assert submission.artifact_version != base


def test_production_composition_registers_required_runtime_factories(tmp_path: Path) -> None:
    config = GovernanceBootstrapConfig("org", tmp_path, bindings(), "a" * 40)
    registry = production_registry(
        config, runtime_builder=lambda workspace, materialize: (object(), object())
    )
    assert registry.factory_names == ("governed_execution", "governed_llm")


def _approved_change(path: str = "change.py"):
    problem = ProblemBrief("p", 1, "title", "problem", "impact", proposed_scope=(path,))
    problem_approval = ProblemApproval(
        "p", 1, problem.fingerprint, "logical.product_owner",
        ProblemDecision.APPROVED_FOR_DESIGN, (path,), (), (), "approved",
    )
    solution = SolutionProposal(
        "s", 1, "p", problem_approval.fingerprint, "Change the approved file.", "minimal",
        ScopeConformance.WITHIN_APPROVED_SCOPE, (path,), (),
        existing_components_reused=(path,), acceptance_invariants=("file changes",),
    )
    approval = SolutionApproval(
        "s", 1, solution.fingerprint, problem_approval.fingerprint,
        "logical.product_owner", SolutionDecision.APPROVED_FOR_IMPLEMENTATION, "approved",
    )
    return problem, solution, approval


class _ProposalProvider:
    provider_id = "implementation.test"

    def __init__(self) -> None:
        self.requests = []

    def propose_patch(self, request):
        self.requests.append(request)
        return PatchCandidate(
            "diff --git a/change.py b/change.py\n"
            "--- a/change.py\n+++ b/change.py\n@@ -1 +1 @@\n-before\n+after\n"
        )


class _PassingTools:
    def run(self, tool, *, cwd):
        return RawToolResult(ToolStatus.PASSED, 0, b"ok", b"")


def _runtime_builder(provider, *, wrong_shared_runtime=False, materializer=None):
    tools = tuple(
        TrustedToolSpec(
            f"test.{kind.value}", kind,
            (str(Path(sys.executable).resolve()), "-c", "pass"),
        )
        for kind in (ToolKind.LINT, ToolKind.TEST, ToolKind.BUILD)
    )

    def build(workspace, commit):
        proposal = ImplementationAgentRuntime(
            provider=provider, allowed_resources=("repository:test",),
        )
        patch_proposal = proposal
        if wrong_shared_runtime:
            patch_proposal = ImplementationAgentRuntime(
                provider=_ProposalProvider(), allowed_resources=("repository:test",),
            )
        patch = GovernedPatchExecutionRuntime(
            proposal_runtime=patch_proposal, workspace_root=workspace, tools=tools,
            tool_runner=_PassingTools(), materialize=materializer or commit,
        )
        return proposal, patch

    return build


def test_governed_coder_generates_applies_and_materializes_one_bound_proposal(tmp_path: Path) -> None:
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@example.test"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=tmp_path, check=True)
    (tmp_path / "change.py").write_text("before\n", encoding="utf-8")
    subprocess.run(["git", "add", "change.py"], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-m", "base"], cwd=tmp_path, check=True, capture_output=True)
    base = subprocess.run(["git", "rev-parse", "HEAD"], cwd=tmp_path, check=True,
                          capture_output=True, text=True).stdout.strip()
    provider = _ProposalProvider()
    executor = GovernedImplementationLifecycleExecutor(
        _runtime_builder(provider), repository_root=tmp_path, base_sha=base,
        organization_id="org",
    )
    problem, solution, approval = _approved_change()

    submission = GovernedCoderProvider("logical.coder", executor, tmp_path, base).implement(
        problem, solution, approval,
    )

    assert len(provider.requests) == 1
    request = provider.requests[0]
    assert request.organization_id == "org"
    assert request.resource == "repository:test"
    assert request.allowed_paths == ("change.py",)
    assert request.context_packet.items[0].canonical()["value"] == {
        "problem": problem.fingerprint,
        "problem_approval": solution.problem_approval_fingerprint,
        "solution": solution.fingerprint,
        "solution_approval": approval.fingerprint,
    }
    assert submission.base_version == base
    assert submission.changed_files == ("change.py",)
    assert subprocess.run(["git", "rev-parse", "HEAD"], cwd=tmp_path, check=True,
                          capture_output=True, text=True).stdout.strip() == base
    assert subprocess.run(["git", "diff", "--name-only", f"{base}...{submission.artifact_version}"],
                          cwd=tmp_path, check=True, capture_output=True,
                          text=True).stdout.splitlines() == ["change.py"]


def test_governed_coder_rejects_nonshared_proposal_runtime_before_patch_execution(tmp_path: Path) -> None:
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@example.test"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=tmp_path, check=True)
    (tmp_path / "change.py").write_text("before\n", encoding="utf-8")
    subprocess.run(["git", "add", "change.py"], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-m", "base"], cwd=tmp_path, check=True, capture_output=True)
    base = subprocess.run(["git", "rev-parse", "HEAD"], cwd=tmp_path, check=True,
                          capture_output=True, text=True).stdout.strip()
    executor = GovernedImplementationLifecycleExecutor(
        _runtime_builder(_ProposalProvider(), wrong_shared_runtime=True),
        repository_root=tmp_path, base_sha=base, organization_id="org",
    )
    with pytest.raises(RuntimeError, match="share one"):
        executor.execute(*_approved_change())
    assert executor.receipt is None


def test_governed_coder_materializer_failure_returns_no_cached_receipt(tmp_path: Path) -> None:
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@example.test"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=tmp_path, check=True)
    (tmp_path / "change.py").write_text("before\n", encoding="utf-8")
    subprocess.run(["git", "add", "change.py"], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-m", "base"], cwd=tmp_path, check=True, capture_output=True)
    base = subprocess.run(["git", "rev-parse", "HEAD"], cwd=tmp_path, check=True,
                          capture_output=True, text=True).stdout.strip()

    def fail(_record):
        raise RuntimeError("materializer unavailable")

    executor = GovernedImplementationLifecycleExecutor(
        _runtime_builder(_ProposalProvider(), materializer=fail),
        repository_root=tmp_path, base_sha=base, organization_id="org",
    )
    with pytest.raises(RuntimeError, match="materialization receipt"):
        executor.execute(*_approved_change())
    assert executor.receipt is None
