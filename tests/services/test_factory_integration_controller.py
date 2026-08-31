from __future__ import annotations

import subprocess
import threading
from dataclasses import replace
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from domain.factory_integration import IntegrationCandidate, IntegrationPlan
from domain.factory_work import (
    CandidateDelivery,
    CandidateSelection,
    ExecutionMode,
    WorkPackage,
    WorkPackageStatus,
    WriteScope,
    fingerprint,
)
from infrastructure.persistence.factory_integration_store import (
    FactoryIntegrationStore,
)
from infrastructure.persistence.factory_store import FactoryStore
from infrastructure.persistence.models import Base
from infrastructure.persistence.side_effect_store import SQLAlchemySideEffectStore
from phase4.authority.engine import AuthorityEngine
from phase4.authority.grants import VerifiedAuthorityGrant
from phase4.authority.models import (
    AuthorityPolicy,
    AuthorityRequest,
    AuthorityRule,
    Decision,
)
from services.factory_integration_controller import (
    FactoryIntegrationController,
    IntegrationError,
)
from services.side_effects import SideEffectCoordinator, SideEffectInProgressError


def git(path: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=path, text=True, capture_output=True, check=True
    ).stdout.strip()


class PassingSuite:
    def run(self, workspace: Path, checks: tuple[str, ...]) -> dict[str, str]:
        assert checks == ("pytest",)
        assert (workspace / "app.py").read_text() == "VALUE = 2\n"
        return {"status": "passed", "tests_run": "1", "failures": "0"}


class BlockingSuite(PassingSuite):
    def __init__(self) -> None:
        self.calls = 0
        self.entered = threading.Event()
        self.release = threading.Event()

    def run(self, workspace: Path, checks: tuple[str, ...]) -> dict[str, str]:
        self.calls += 1
        self.entered.set()
        assert self.release.wait(timeout=5)
        return super().run(workspace, checks)


class FailTerminalSaveOnce:
    def __init__(self, store: FactoryIntegrationStore) -> None:
        self.store = store
        self.failed = False

    def __getattr__(self, name):
        return getattr(self.store, name)

    def save_plan(self, value, *, expected_version):
        if value.status.value == "succeeded" and not self.failed:
            self.failed = True
            raise RuntimeError("simulated crash before terminal plan commit")
        return self.store.save_plan(value, expected_version=expected_version)


def setup(tmp_path: Path, suite: PassingSuite | None = None):
    repository = tmp_path / "repo"
    remote = tmp_path / "remote.git"
    repository.mkdir()
    git(repository, "init", "-b", "main")
    git(repository, "config", "user.name", "Test")
    git(repository, "config", "user.email", "test@example.test")
    (repository / "app.py").write_text("VALUE = 1\n")
    git(repository, "add", ".")
    git(repository, "commit", "-m", "base")
    base = git(repository, "rev-parse", "HEAD")
    subprocess.run(["git", "init", "--bare", str(remote)], check=True)
    git(repository, "remote", "add", "origin", str(remote))
    git(repository, "switch", "-c", "candidate")
    (repository / "app.py").write_text("VALUE = 2\n")
    git(repository, "add", ".")
    git(repository, "commit", "-m", "candidate")
    head = git(repository, "rev-parse", "HEAD")
    git(repository, "switch", "main")

    engine = create_engine(
        f"sqlite:///{tmp_path / 'state.db'}",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine, expire_on_commit=False)
    factory = FactoryStore(sessions)
    integrations = FactoryIntegrationStore(sessions)
    package = WorkPackage(
        organization_id="org-1",
        work_package_id="a" * 64,
        logical_task_id="task-1",
        workflow_id="workflow-1",
        requirements_fingerprint="b" * 64,
        architecture_fingerprint="c" * 64,
        contract_fingerprint="d" * 64,
        base_sha=base,
        dependency_ids=(),
        criterion_ids=("criterion-1",),
        required_checks=("pytest",),
        write_scope=WriteScope(("app.py",)),
        execution_mode=ExecutionMode.SINGLE,
        candidate_count=1,
        allocation_id="implementers",
        allocation_version=1,
        policy_fingerprint="e" * 64,
        token_budget=100,
        time_budget_seconds=60,
        idempotency_key="package-1",
        status=WorkPackageStatus.DELIVERED,
    )
    factory.create_package(package)
    candidate = CandidateDelivery(
        organization_id="org-1",
        candidate_id="candidate-1",
        work_package_id=package.work_package_id,
        work_package_fingerprint=package.content_fingerprint,
        execution_id="execution-1",
        assignment_id="f" * 64,
        base_sha=base,
        branch="factory/execution-1/candidate-1",
        head_sha=head,
        commit_shas=(head,),
        patch_fingerprint="1" * 64,
        affected_paths=("app.py",),
        attestations=("pytest",),
    )
    factory.append_candidate(candidate)
    selection = CandidateSelection(
        organization_id="org-1",
        selection_id="4" * 64,
        logical_task_id=package.logical_task_id,
        work_package_fingerprint=package.content_fingerprint,
        candidate_ids=(candidate.candidate_id,),
        rubric_fingerprint="5" * 64,
        evaluation_ids=("evaluation-1",),
        excluded_candidate_ids=(),
        winner_candidate_id=candidate.candidate_id,
        evaluator_assignment_id="6" * 64,
        authority_decision_id="7" * 64,
    )
    factory.append_selection(selection)
    plan = IntegrationPlan(
        organization_id="org-1",
        plan_id="plan-1",
        workflow_id="workflow-1",
        repository="test/repo",
        base_sha=base,
        candidates=(
            IntegrationCandidate(
                candidate_id=candidate.candidate_id,
                selection_id=selection.selection_id,
                work_package_fingerprint=package.content_fingerprint,
                head_sha=head,
                commit_shas=(head,),
            ),
        ),
        dependency_evidence=("dag-verified",),
        compatibility_evidence=("scope-verified",),
        integration_branch="factory/integration/workflow-1",
        required_checks=("pytest",),
        idempotency_key="integrate:workflow-1",
    )
    integrations.create_plan(plan)
    coordinator = SideEffectCoordinator(SQLAlchemySideEffectStore(sessions))
    controller = FactoryIntegrationController(
        repository,
        candidates=factory,
        plans=integrations,
        side_effects=coordinator,
        suite_runner=suite or PassingSuite(),
    )
    return repository, factory, integrations, controller, plan


def grant(plan: IntegrationPlan) -> VerifiedAuthorityGrant:
    request = AuthorityRequest.create(
        "integration-controller",
        "factory.integrate",
        f"repository:{plan.repository}",
        "context-1",
        organization_id=plan.organization_id,
        capability="factory.integrate",
        parameters={
            "plan_fingerprint": plan.content_fingerprint,
            "base_sha": plan.base_sha,
        },
    )
    policy = AuthorityPolicy(
        "integration-policy",
        "1",
        (
            AuthorityRule(
                "allow-integration",
                "factory.integrate",
                f"repository:{plan.repository}",
                Decision.ALLOW,
                agent_identity="integration-controller",
            ),
        ),
    )
    return VerifiedAuthorityGrant.from_decision(
        AuthorityEngine(policy).evaluate(request)
    )


def test_integrates_exact_candidate_and_returns_attested_handoff(
    tmp_path: Path,
) -> None:
    repository, _, store, controller, plan = setup(tmp_path)
    receipt, handoff, replayed = controller.integrate(plan, grant(plan))
    assert not replayed
    assert receipt.status.value == "succeeded"
    assert handoff is not None and handoff.base_sha == plan.base_sha
    assert handoff.patch_fingerprint == fingerprint(handoff.patch_content)
    assert git(repository, "ls-remote", "--heads", "origin", plan.integration_branch)
    assert store.get_plan("org-1", plan.plan_id).status.value == "succeeded"
    replay_receipt, replay_handoff, replayed = controller.integrate(plan, grant(plan))
    assert replayed and replay_receipt.receipt_id == receipt.receipt_id
    assert replay_handoff == handoff


def test_rejects_candidate_head_changed_after_plan(tmp_path: Path) -> None:
    _, factory, _, controller, plan = setup(tmp_path)
    actual = factory.get_candidate("org-1", "candidate-1")
    changed = IntegrationCandidate(
        candidate_id=actual.candidate_id,
        selection_id=plan.candidates[0].selection_id,
        work_package_fingerprint=actual.work_package_fingerprint,
        head_sha="9" * 40,
        commit_shas=("9" * 40,),
    )
    altered = IntegrationPlan(
        **{**plan.__dict__, "candidates": (changed,), "plan_id": "plan-2"}
    )
    with pytest.raises(IntegrationError, match="evidence changed"):
        controller.integrate(altered, grant(altered))


def test_rejects_grant_for_another_plan(tmp_path: Path) -> None:
    _, _, _, controller, plan = setup(tmp_path)
    other = IntegrationPlan(**{**plan.__dict__, "plan_id": "plan-other"})
    with pytest.raises(IntegrationError, match="authority grant"):
        controller.integrate(plan, grant(other))


def test_two_workers_produce_one_integration_side_effect(tmp_path: Path) -> None:
    suite = BlockingSuite()
    _, _, store, controller, plan = setup(tmp_path, suite)
    outcomes = []
    worker = threading.Thread(
        target=lambda: outcomes.append(controller.integrate(plan, grant(plan)))
    )
    worker.start()
    assert suite.entered.wait(timeout=5)
    with pytest.raises(SideEffectInProgressError, match="already in progress"):
        controller.integrate(plan, grant(plan))
    assert store.get_plan("org-1", plan.plan_id).status.value == "running"
    suite.release.set()
    worker.join(timeout=5)
    assert not worker.is_alive()
    assert suite.calls == 1
    assert len(outcomes) == 1


def test_conflicting_candidate_commits_halt_without_release_handoff(
    tmp_path: Path,
) -> None:
    repository, factory, integrations, controller, plan = setup(tmp_path)
    git(repository, "switch", "-c", "candidate-2", "main")
    (repository / "app.py").write_text("VALUE = 3\n")
    git(repository, "add", ".")
    git(repository, "commit", "-m", "competing candidate")
    second_head = git(repository, "rev-parse", "HEAD")
    git(repository, "switch", "main")
    first_package = factory.get_package("org-1", "a" * 64)
    second_package = replace(
        first_package,
        work_package_id="8" * 64,
        logical_task_id="task-2",
        idempotency_key="package-2",
    )
    factory.create_package(second_package)
    second = CandidateDelivery(
        organization_id="org-1",
        candidate_id="candidate-2",
        work_package_id=second_package.work_package_id,
        work_package_fingerprint=second_package.content_fingerprint,
        execution_id="execution-2",
        assignment_id="2" * 64,
        base_sha=plan.base_sha,
        branch="factory/execution-2/candidate-2",
        head_sha=second_head,
        commit_shas=(second_head,),
        patch_fingerprint="3" * 64,
        affected_paths=("app.py",),
        attestations=("pytest",),
    )
    factory.append_candidate(second)
    second_selection = CandidateSelection(
        organization_id="org-1",
        selection_id="9" * 64,
        logical_task_id=second_package.logical_task_id,
        work_package_fingerprint=second_package.content_fingerprint,
        candidate_ids=(second.candidate_id,),
        rubric_fingerprint="a" * 64,
        evaluation_ids=("evaluation-2",),
        excluded_candidate_ids=(),
        winner_candidate_id=second.candidate_id,
        evaluator_assignment_id="b" * 64,
        authority_decision_id="c" * 64,
    )
    factory.append_selection(second_selection)
    competing = IntegrationPlan(
        **{
            **plan.__dict__,
            "plan_id": "plan-conflict",
            "candidates": (
                plan.candidates[0],
                IntegrationCandidate(
                    candidate_id=second.candidate_id,
                    selection_id=second_selection.selection_id,
                    work_package_fingerprint=second.work_package_fingerprint,
                    head_sha=second.head_sha,
                    commit_shas=second.commit_shas,
                ),
            ),
            "integration_branch": "factory/integration/conflict",
            "idempotency_key": "integrate:conflict",
        }
    )
    integrations.create_plan(competing)
    receipt, handoff, _ = controller.integrate(competing, grant(competing))
    assert receipt.status.value == "conflict"
    assert receipt.conflict_paths == ("app.py",)
    assert handoff is None
    assert not git(
        repository,
        "ls-remote",
        "--heads",
        "origin",
        competing.integration_branch,
    )


def test_restart_replays_completed_effect_and_finishes_running_plan(
    tmp_path: Path,
) -> None:
    _, _, store, controller, plan = setup(tmp_path)
    controller._plans = FailTerminalSaveOnce(store)
    with pytest.raises(RuntimeError, match="simulated crash"):
        controller.integrate(plan, grant(plan))
    assert store.get_plan("org-1", plan.plan_id).status.value == "running"
    receipt, handoff, replayed = controller.integrate(plan, grant(plan))
    assert replayed and handoff is not None
    assert receipt.status.value == "succeeded"
    assert store.get_plan("org-1", plan.plan_id).status.value == "succeeded"
