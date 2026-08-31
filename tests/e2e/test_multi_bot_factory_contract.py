"""MBF-09..14 acceptance proofs using real SQLAlchemy and temporary Git repos."""

from __future__ import annotations

import subprocess
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from sqlalchemy import create_engine, select, update
from sqlalchemy.orm import sessionmaker

from domain.factory_work import (
    CandidateDelivery,
    CandidateSelection,
    ExecutionMode,
    WorkPackageStatus,
    WriteScope,
    fingerprint,
)
from execution.factory_task_synthesizer import FactoryTaskSpec, FactoryTaskSynthesizer
from infrastructure.persistence.factory_store import (
    FactoryStore,
    FactoryStoreConflictError,
)
from infrastructure.persistence.models import Base
from infrastructure.persistence.side_effect_store import SQLAlchemySideEffectStore
from infrastructure.runtime.queue import DatabaseQueue, QueueMessageModel
from phase4.authority.engine import AuthorityEngine
from phase4.authority.grants import VerifiedAuthorityGrant
from phase4.authority.models import (
    AuthorityPolicy,
    AuthorityRequest,
    AuthorityRule,
    Decision,
)
from phase4.execution.durable_ledger import SqlAlchemyReplayLedger
from phase4.execution.models import ExecutionResult, ExecutionStatus
from phase4.execution.replay_ledger import ClaimOutcomeKind
from services.factory_integration_controller import IntegrationError
from services.factory_scheduler import FactoryScheduler
from services.factory_workspace import FactoryWorkspaceManager
from services.side_effects import SideEffectCoordinator, SideEffectInProgressError
from tests.services.test_factory_integration_controller import (
    BlockingSuite,
)
from tests.services.test_factory_integration_controller import (
    grant as integration_grant,
)
from tests.services.test_factory_integration_controller import (
    setup as integration_setup,
)


def git(path: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=path, text=True, capture_output=True, check=True
    ).stdout.strip()


def repository(tmp_path: Path, files: int = 20) -> tuple[Path, str]:
    root, remote = tmp_path / "repo", tmp_path / "remote.git"
    root.mkdir()
    git(root, "init", "-b", "main")
    git(root, "config", "user.name", "Factory Test")
    git(root, "config", "user.email", "factory@example.test")
    (root / "components").mkdir()
    for index in range(files):
        (root / "components" / f"component-{index}.txt").write_text("base\n")
    git(root, "add", ".")
    git(root, "commit", "-m", "factory base")
    base = git(root, "rev-parse", "HEAD")
    subprocess.run(["git", "init", "--bare", str(remote)], check=True)
    git(root, "remote", "add", "origin", str(remote))
    return root, base


def database(tmp_path: Path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'factory.db'}",
        connect_args={"check_same_thread": False, "timeout": 30},
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)


class DeterministicImplementationBot:
    """A fake provider that still writes through the real governed workspace."""

    def implement(self, workspace: Path, index: int) -> None:
        target = workspace / "components" / f"component-{index}.txt"
        target.write_text(f"implemented-by-bot-{index}\n")


def result(execution_id: str, candidate_id: str) -> ExecutionResult:
    return ExecutionResult(
        execution_id=execution_id,
        request_id=f"request-{candidate_id}",
        authority_policy_id="factory-policy",
        authority_policy_version="1",
        agent_identity=candidate_id,
        action="factory.implement",
        resource=f"candidate:{candidate_id}",
        context_packet_id="factory-context",
        status=ExecutionStatus.SUCCEEDED,
        adapter_id="deterministic-test-provider",
        output=(("candidate_id", candidate_id),),
        error=None,
        executed_at=datetime.now(timezone.utc).isoformat(),
    )


def release_grant(receipt_id: str, patch_id: str) -> VerifiedAuthorityGrant:
    request = AuthorityRequest.create(
        "release-controller",
        "release.publish",
        "repository:test/repo",
        "release-context",
        organization_id="org-1",
        capability="release.publish",
        parameters={
            "integration_receipt_id": receipt_id,
            "patch_id": patch_id,
            "base_branch": "main",
        },
    )
    policy = AuthorityPolicy(
        "release-policy",
        "1",
        (
            AuthorityRule(
                "allow-release",
                "release.publish",
                "repository:test/repo",
                Decision.ALLOW,
                agent_identity="release-controller",
            ),
        ),
    )
    return VerifiedAuthorityGrant.from_decision(
        AuthorityEngine(policy).evaluate(request)
    )


def test_mbf09_twenty_workers_have_isolated_claims_worktrees_and_branches(
    tmp_path: Path,
) -> None:
    root, base = repository(tmp_path)
    sessions = database(tmp_path)
    queue = DatabaseQueue(sessions, organization_id="org-1", lease_seconds=30)
    scheduler = FactoryScheduler(queue)
    store = FactoryStore(sessions)
    side_effects = SideEffectCoordinator(SQLAlchemySideEffectStore(sessions))
    tasks = tuple(
        FactoryTaskSpec(
            logical_task_id=f"task-{index:02d}",
            criterion_ids=(f"criterion-{index:02d}",),
            required_checks=("deterministic-provider",),
            write_scope=WriteScope((f"components/component-{index}.txt",)),
        )
        for index in range(20)
    )
    packages = FactoryTaskSynthesizer().synthesize(
        organization_id="org-1",
        workflow_id="workflow-20",
        requirements_fingerprint="1" * 64,
        architecture_fingerprint="2" * 64,
        contract_fingerprint="3" * 64,
        base_sha=base,
        tasks=tasks,
        execution_mode=ExecutionMode.SINGLE,
        candidate_count=1,
        allocation_id="twenty-bots",
        allocation_version=1,
        policy_fingerprint="4" * 64,
        token_budget=100,
        time_budget_seconds=60,
    )
    for package in packages:
        store.create_package(package)
        scheduler.publish(package)
        store.save_package(
            package.transition(WorkPackageStatus.PUBLISHED), expected_version=0
        )

    bot = DeterministicImplementationBot()
    barrier = threading.Barrier(20)

    def work(worker_number: int) -> CandidateDelivery:
        worker_id = f"worker-{worker_number:02d}"
        barrier.wait(timeout=10)
        message = queue.claim("factory.work", worker_id)
        assert message is not None and message.lease_id
        package = store.get_package("org-1", message.payload["work_package_id"])
        assert package is not None
        assert package.content_fingerprint == message.payload["fingerprint"]
        index = int(package.logical_task_id.removeprefix("task-"))
        execution_id = f"execution-{index:02d}"
        candidate_id = f"candidate-{index:02d}"
        ledger = SqlAlchemyReplayLedger(sessions, organization_id="org-1")
        claim = ledger.try_claim(execution_id, request_id=f"request-{index:02d}")
        assert claim.kind is ClaimOutcomeKind.ACQUIRED
        assert claim.record and claim.record.fencing_token
        running = package.transition(WorkPackageStatus.RUNNING)
        store.save_package(running, expected_version=package.version)
        manager = FactoryWorkspaceManager(root)
        workspace = manager.create(
            execution_id=execution_id,
            candidate_id=candidate_id,
            base_sha=base,
        )
        try:
            bot.implement(workspace.path, index)
            git(workspace.path, "add", ".")
            git(workspace.path, "commit", "-m", f"implement component {index}")
            evidence = manager.attest(workspace, package.write_scope)
            manager.publish(
                workspace,
                organization_id="org-1",
                coordinator=side_effects,
            )
            delivery = CandidateDelivery(
                organization_id="org-1",
                candidate_id=candidate_id,
                work_package_id=package.work_package_id,
                work_package_fingerprint=package.content_fingerprint,
                execution_id=execution_id,
                assignment_id=fingerprint({"candidate": candidate_id}),
                base_sha=base,
                branch=evidence["branch"],
                head_sha=evidence["head_sha"],
                commit_shas=evidence["commit_shas"],
                patch_fingerprint=evidence["patch_fingerprint"],
                affected_paths=evidence["affected_paths"],
                attestations=("deterministic-provider",),
            )
            store.append_candidate(delivery)
            ledger.complete_succeeded(
                execution_id,
                result(execution_id, candidate_id),
                fencing_token=claim.record.fencing_token,
            )
            store.save_package(
                running.transition(WorkPackageStatus.DELIVERED),
                expected_version=running.version,
            )
            queue.ack(message.id, worker_id, message.lease_id)
            return delivery
        finally:
            manager.cleanup(workspace)

    with ThreadPoolExecutor(max_workers=20) as pool:
        deliveries = tuple(pool.map(work, range(20)))

    assert len({item.branch for item in deliveries}) == 20
    assert len({path for item in deliveries for path in item.affected_paths}) == 20
    remote_branches = git(root, "ls-remote", "--heads", "origin").splitlines()
    assert len([line for line in remote_branches if "factory/execution-" in line]) == 20
    with sessions() as session:
        completed = session.scalars(
            select(QueueMessageModel).where(QueueMessageModel.status == "completed")
        ).all()
        assert len(completed) == 20


def test_mbf10_reclaimed_queue_and_execution_reject_stale_tokens(
    tmp_path: Path,
) -> None:
    sessions = database(tmp_path)
    queue = DatabaseQueue(sessions, organization_id="org-1", lease_seconds=1)
    message_id = queue.publish("factory.work", {"work_package_id": "package-1"})
    first = queue.claim("factory.work", "worker-old")
    assert first and first.lease_id
    with sessions() as session, session.begin():
        session.execute(
            update(QueueMessageModel)
            .where(QueueMessageModel.id == message_id)
            .values(lease_until=datetime.now(timezone.utc) - timedelta(seconds=1))
        )
    second = queue.claim("factory.work", "worker-new")
    assert second and second.lease_id != first.lease_id
    with pytest.raises(ValueError, match="not leased"):
        queue.ack(message_id, "worker-old", first.lease_id)

    ledger = SqlAlchemyReplayLedger(
        sessions, organization_id="org-1", claim_lease_seconds=1
    )
    start = datetime.now(timezone.utc)
    old = ledger.try_claim("execution-stale", now=start)
    new = ledger.try_claim("execution-stale", now=start + timedelta(seconds=2))
    assert old.record and new.record
    with pytest.raises(RuntimeError, match="fencing token mismatch"):
        ledger.complete_succeeded(
            "execution-stale",
            result("execution-stale", "candidate-stale"),
            fencing_token=old.record.fencing_token,
        )


def test_mbf11_three_competing_candidates_yield_at_most_one_winner(
    tmp_path: Path,
) -> None:
    root, base = repository(tmp_path, files=1)
    sessions = database(tmp_path)
    store = FactoryStore(sessions)
    package = FactoryTaskSynthesizer().synthesize(
        organization_id="org-1",
        workflow_id="workflow-compete",
        requirements_fingerprint="1" * 64,
        architecture_fingerprint="2" * 64,
        contract_fingerprint="3" * 64,
        base_sha=base,
        tasks=(
            FactoryTaskSpec(
                "task-compete",
                ("criterion",),
                ("pytest",),
                WriteScope(("components/component-0.txt",)),
            ),
        ),
        execution_mode=ExecutionMode.COMPETING,
        candidate_count=3,
        allocation_id="competitors",
        allocation_version=1,
        policy_fingerprint="4" * 64,
        token_budget=100,
        time_budget_seconds=60,
    )[0]
    store.create_package(package)
    deliveries = []
    for index in range(3):
        git(root, "switch", "-c", f"competitor-{index}", "main")
        target = root / "components" / "component-0.txt"
        target.write_text(f"candidate-{index}\n")
        git(root, "add", ".")
        git(root, "commit", "-m", f"candidate {index}")
        head = git(root, "rev-parse", "HEAD")
        git(root, "switch", "main")
        delivery = CandidateDelivery(
            organization_id="org-1",
            candidate_id=f"candidate-{index}",
            work_package_id=package.work_package_id,
            work_package_fingerprint=package.content_fingerprint,
            execution_id=f"execution-{index}",
            assignment_id=fingerprint({"assignment": index}),
            base_sha=base,
            branch=f"factory/execution-{index}/candidate-{index}",
            head_sha=head,
            commit_shas=(head,),
            patch_fingerprint=fingerprint(git(root, "diff", base, head)),
            affected_paths=("components/component-0.txt",),
            attestations=("pytest",),
        )
        store.append_candidate(delivery)
        deliveries.append(delivery)

    candidates = tuple(item.candidate_id for item in deliveries)

    def select_winner(index: int) -> str:
        selection = CandidateSelection(
            organization_id="org-1",
            selection_id=fingerprint({"selection": index}),
            logical_task_id=package.logical_task_id,
            work_package_fingerprint=package.content_fingerprint,
            candidate_ids=candidates,
            rubric_fingerprint="5" * 64,
            evaluation_ids=(f"evaluation-{index}",),
            excluded_candidate_ids=tuple(
                item for item in candidates if item != f"candidate-{index}"
            ),
            winner_candidate_id=f"candidate-{index}",
            evaluator_assignment_id=fingerprint({"evaluator": index}),
            authority_decision_id=fingerprint({"authority": index}),
        )
        try:
            store.append_selection(selection)
            return selection.winner_candidate_id
        except FactoryStoreConflictError:
            return "conflict"

    with ThreadPoolExecutor(max_workers=3) as pool:
        outcomes = tuple(pool.map(select_winner, range(3)))
    assert sum(item != "conflict" for item in outcomes) == 1


class MutableClock:
    def __init__(self) -> None:
        self.now = datetime.now(timezone.utc)

    def __call__(self) -> datetime:
        return self.now


class FailFirstCompletion:
    def __init__(self, store: SQLAlchemySideEffectStore) -> None:
        self.store = store
        self.failed = False

    def claim(self, *args):
        return self.store.claim(*args)

    def complete(self, *args):
        if not self.failed:
            self.failed = True
            raise RuntimeError("simulated crash after remote push")
        return self.store.complete(*args)

    def fail(self, *args):
        return self.store.fail(*args)


def test_mbf12_push_crash_reconciles_one_remote_branch(tmp_path: Path) -> None:
    root, base = repository(tmp_path, files=1)
    sessions = database(tmp_path)
    clock = MutableClock()
    durable = SQLAlchemySideEffectStore(sessions, lease_seconds=1, clock=clock)
    failing = FailFirstCompletion(durable)
    manager = FactoryWorkspaceManager(root)
    workspace = manager.create(
        execution_id="execution-crash",
        candidate_id="candidate-crash",
        base_sha=base,
    )
    target = workspace.path / "components" / "component-0.txt"
    target.write_text("crash-safe\n")
    git(workspace.path, "add", ".")
    git(workspace.path, "commit", "-m", "crash-safe candidate")
    try:
        with pytest.raises(RuntimeError, match="simulated crash"):
            manager.publish(
                workspace,
                organization_id="org-1",
                coordinator=SideEffectCoordinator(failing),
            )
        first_remote = git(root, "ls-remote", "--heads", "origin").splitlines()
        assert len(first_remote) == 1
        clock.now += timedelta(seconds=2)
        result, replayed = manager.publish(
            workspace,
            organization_id="org-1",
            coordinator=SideEffectCoordinator(failing),
        )
        assert not replayed and result["reconciled"]
        second_remote = git(root, "ls-remote", "--heads", "origin").splitlines()
        assert second_remote == first_remote
    finally:
        manager.cleanup(workspace)


def test_mbf13_changed_base_invalidates_candidate_and_authority_binding(
    tmp_path: Path,
) -> None:
    integration_root = tmp_path / "base-invalidation"
    integration_root.mkdir()
    _, _, _, controller, plan = integration_setup(integration_root)
    stale = replace(plan, base_sha="9" * 40)
    with pytest.raises(IntegrationError, match="authority grant"):
        controller.integrate(stale, integration_grant(plan))
    with pytest.raises(IntegrationError, match="evidence changed"):
        controller.integrate(stale, integration_grant(stale))


def test_mbf14_twenty_integrators_converge_to_one_receipt_and_one_pr(
    tmp_path: Path,
) -> None:
    suite = BlockingSuite()
    integration_root = tmp_path / "integration"
    integration_root.mkdir()
    _, _, store, controller, plan = integration_setup(integration_root, suite)
    outcomes = []
    errors = []

    def integrate() -> None:
        try:
            outcomes.append(controller.integrate(plan, integration_grant(plan)))
        except SideEffectInProgressError:
            errors.append("in_progress")

    winner = threading.Thread(target=integrate)
    winner.start()
    assert suite.entered.wait(timeout=5)
    with ThreadPoolExecutor(max_workers=19) as pool:
        tuple(pool.map(lambda _: integrate(), range(19)))
    suite.release.set()
    winner.join(timeout=5)
    assert not winner.is_alive()
    assert suite.calls == 1
    assert len(outcomes) == 1 and len(errors) == 19
    receipt = store.get_receipt_for_plan("org-1", plan.content_fingerprint)
    assert receipt is not None and receipt.status.value == "succeeded"

    pr_calls = 0
    pr_lock = threading.Lock()
    pr_entered = threading.Event()
    pr_release = threading.Event()
    authority = release_grant(receipt.receipt_id, plan.content_fingerprint)

    def create_pr() -> dict:
        nonlocal pr_calls
        assert authority.verified
        assert authority.action == "release.publish"
        assert (
            dict(authority.parameters)["integration_receipt_id"] == receipt.receipt_id
        )
        with pr_lock:
            pr_calls += 1
        pr_entered.set()
        assert pr_release.wait(timeout=5)
        return {"pr_number": 1, "pr_url": "https://example.test/pr/1"}

    def publish_release() -> dict:
        result, _ = controller._side_effects.execute(
            organization_id="org-1",
            action="release.publish",
            idempotency_key=f"release:{receipt.receipt_id}",
            request_data={
                "integration_receipt_id": receipt.receipt_id,
                "plan_fingerprint": plan.content_fingerprint,
            },
            operation=create_pr,
        )
        return result

    release_outcomes = []
    release_errors = []

    def attempt_release() -> None:
        try:
            release_outcomes.append(publish_release())
        except SideEffectInProgressError:
            release_errors.append("in_progress")

    release_winner = threading.Thread(target=attempt_release)
    release_winner.start()
    assert pr_entered.wait(timeout=5)
    with ThreadPoolExecutor(max_workers=19) as pool:
        tuple(pool.map(lambda _: attempt_release(), range(19)))
    pr_release.set()
    release_winner.join(timeout=5)
    assert not release_winner.is_alive()
    assert len(release_outcomes) == 1 and len(release_errors) == 19
    with ThreadPoolExecutor(max_workers=20) as pool:
        published = tuple(pool.map(lambda _: publish_release(), range(20)))
    assert pr_calls == 1
    assert {item["pr_url"] for item in published} == {"https://example.test/pr/1"}
