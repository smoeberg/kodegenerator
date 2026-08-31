from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from domain.factory_work import (
    CandidateDelivery,
    CandidateSelection,
    ExecutionMode,
    WorkPackage,
    WorkPackageStatus,
    WriteScope,
)
from infrastructure.persistence.factory_store import FactoryStore
from infrastructure.persistence.models import Base


def package(org="org-1"):
    return WorkPackage(
        organization_id=org,
        work_package_id="a" * 64,
        logical_task_id="task-1",
        workflow_id="workflow-1",
        requirements_fingerprint="b" * 64,
        architecture_fingerprint="c" * 64,
        contract_fingerprint="d" * 64,
        base_sha="e" * 40,
        dependency_ids=(),
        criterion_ids=("ac-1",),
        required_checks=("pytest",),
        write_scope=WriteScope(("src",)),
        execution_mode=ExecutionMode.SINGLE,
        candidate_count=1,
        allocation_id="implementers",
        allocation_version=1,
        policy_fingerprint="f" * 64,
        token_budget=100,
        time_budget_seconds=60,
        idempotency_key="factory:one",
        status=WorkPackageStatus.READY,
    )


def test_package_replay_occ_and_tenant_scope() -> None:
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False, future=True)
    store = FactoryStore(factory)
    original = package()
    assert store.create_package(original) == original
    assert (
        store.create_package(original).content_fingerprint
        == original.content_fingerprint
    )
    assert store.get_package("org-2", original.work_package_id) is None
    published = original.transition(WorkPackageStatus.PUBLISHED)
    store.save_package(published, expected_version=0)
    assert (
        store.get_package("org-1", original.work_package_id).status
        is WorkPackageStatus.PUBLISHED
    )


def test_candidate_selection_is_bound_to_durable_candidates() -> None:
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False, future=True)
    store = FactoryStore(factory)
    work = package()
    store.create_package(work)
    candidate = CandidateDelivery(
        organization_id="org-1",
        candidate_id="candidate-1",
        work_package_id=work.work_package_id,
        work_package_fingerprint=work.content_fingerprint,
        execution_id="execution-1",
        assignment_id="1" * 64,
        base_sha="2" * 40,
        branch="factory/execution-1/candidate-1",
        head_sha="3" * 40,
        commit_shas=("3" * 40,),
        patch_fingerprint="4" * 64,
        affected_paths=("src/app.py",),
        attestations=("pytest",),
    )
    store.append_candidate(candidate)
    selection = CandidateSelection(
        organization_id="org-1",
        selection_id="5" * 64,
        logical_task_id=work.logical_task_id,
        work_package_fingerprint=work.content_fingerprint,
        candidate_ids=(candidate.candidate_id,),
        rubric_fingerprint="6" * 64,
        evaluation_ids=("evaluation-1",),
        excluded_candidate_ids=(),
        winner_candidate_id=candidate.candidate_id,
        evaluator_assignment_id="7" * 64,
        authority_decision_id="8" * 64,
    )
    assert store.append_selection(selection) == selection
