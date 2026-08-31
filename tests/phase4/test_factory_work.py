import pytest

from domain.factory_work import ExecutionMode, WorkPackageStatus, WriteScope
from execution.factory_task_synthesizer import FactoryTaskSpec, FactoryTaskSynthesizer


def synthesize(tasks):
    return FactoryTaskSynthesizer().synthesize(
        organization_id="org-1",
        workflow_id="workflow-1",
        requirements_fingerprint="a" * 64,
        architecture_fingerprint="b" * 64,
        contract_fingerprint="c" * 64,
        base_sha="d" * 40,
        tasks=tasks,
        execution_mode=ExecutionMode.COMPETING,
        candidate_count=3,
        allocation_id="implementers",
        allocation_version=1,
        policy_fingerprint="e" * 64,
        token_budget=1000,
        time_budget_seconds=300,
    )


def test_overlapping_scopes_become_dependency_edges() -> None:
    packages = synthesize(
        (
            FactoryTaskSpec("api", ("ac-1",), ("pytest",), WriteScope(("src/api",))),
            FactoryTaskSpec(
                "auth", ("ac-2",), ("pytest",), WriteScope(("src/api/auth",))
            ),
        )
    )
    assert packages[0].status is WorkPackageStatus.READY
    assert packages[1].dependency_ids == ("api",)
    assert packages[1].status is WorkPackageStatus.BLOCKED
    replay = synthesize(
        tuple(
            reversed(
                (
                    FactoryTaskSpec(
                        "api", ("ac-1",), ("pytest",), WriteScope(("src/api",))
                    ),
                    FactoryTaskSpec(
                        "auth", ("ac-2",), ("pytest",), WriteScope(("src/api/auth",))
                    ),
                )
            )
        )
    )
    assert tuple(item.content_fingerprint for item in packages) == tuple(
        item.content_fingerprint for item in replay
    )


def test_cycle_and_invalid_candidate_mode_fail_closed() -> None:
    with pytest.raises(ValueError, match="cycle"):
        synthesize(
            (
                FactoryTaskSpec(
                    "one", ("a",), ("test",), WriteScope(("one",)), ("two",)
                ),
                FactoryTaskSpec(
                    "two", ("b",), ("test",), WriteScope(("two",)), ("one",)
                ),
            )
        )
