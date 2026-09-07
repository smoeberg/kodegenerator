from datetime import datetime, timedelta, timezone

import pytest

from domain.capability import Capability
from domain.work_queue import (
    DependencyVersionBinding,
    ImmutableVersionRef,
    WorkUnit,
    WorkUnitContractError,
    WorkUnitState,
    WorkerLease,
)


CAPABILITY = Capability(id="capability.work", name="Work Capability")


def test_required_work_unit_states_exist() -> None:
    assert {state.name for state in WorkUnitState} == {
        "PENDING",
        "READY",
        "CLAIMED",
        "AWAITING_REVIEW",
        "REJECTED",
        "APPROVED",
        "FAILED",
    }


def test_immutable_version_ref_is_domain_agnostic() -> None:
    ref = ImmutableVersionRef(kind="document_revision", value="revision-42")
    assert ref.kind == "document_revision"
    assert ref.value == "revision-42"


def test_required_capability_references_existing_dor_capability() -> None:
    unit = WorkUnit(title="Build feature", required_capability=CAPABILITY)
    assert unit.required_capability is CAPABILITY
    assert isinstance(unit.required_capability, Capability)


def test_dependency_binds_work_unit_to_exact_immutable_version() -> None:
    ref = ImmutableVersionRef(kind="git_commit", value="a" * 40)
    binding = DependencyVersionBinding(work_unit_id="WU-001", version=ref)
    assert binding.work_unit_id == "WU-001"
    assert binding.version == ref


def test_invalid_domain_values_are_rejected() -> None:
    with pytest.raises(WorkUnitContractError):
        ImmutableVersionRef(kind=" ", value="revision")

    with pytest.raises(WorkUnitContractError):
        WorkUnit(title="Build feature", required_capability=None)  # type: ignore[arg-type]

    with pytest.raises(WorkUnitContractError):
        WorkerLease(
            lease_id="lease-1",
            worker_id="worker-1",
            claimed_at=datetime.now(timezone.utc),
            expires_at=datetime.now(timezone.utc) - timedelta(seconds=1),
        )
