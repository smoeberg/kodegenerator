from domain.capability import Capability
from domain.work_queue import WorkUnit, WorkUnitState
from domain.work_queue_readiness import is_ready, is_worker_eligible
from phase4.agent_registry.models import AgentVersion, Capability as RegistryCapability


def capability(capability_id: str, name: str) -> Capability:
    return Capability(id=capability_id, name=name)


def work_unit(
    work_unit_id: str = "WU-001",
    state: WorkUnitState = WorkUnitState.PENDING,
    depends_on: tuple[str, ...] = (),
    required_capability_id: str = "capability.work",
) -> WorkUnit:
    return WorkUnit(
        id=work_unit_id,
        title="Work",
        required_capability=capability(required_capability_id, "Work Capability"),
        state=state,
        depends_on=depends_on,
    )


def test_pending_with_zero_dependencies_is_ready() -> None:
    unit = work_unit()
    assert is_ready(unit, {}) is True


def test_pending_with_all_dependencies_approved_is_ready() -> None:
    unit = work_unit(depends_on=("DEP-1", "DEP-2"))
    dependencies = {
        "DEP-1": work_unit("DEP-1", WorkUnitState.APPROVED),
        "DEP-2": work_unit("DEP-2", WorkUnitState.APPROVED),
    }
    assert is_ready(unit, dependencies) is True


def test_pending_dependency_is_not_ready() -> None:
    unit = work_unit(depends_on=("DEP-1",))
    assert is_ready(unit, {"DEP-1": work_unit("DEP-1", WorkUnitState.PENDING)}) is False


def test_rejected_dependency_is_not_ready() -> None:
    unit = work_unit(depends_on=("DEP-1",))
    assert is_ready(unit, {"DEP-1": work_unit("DEP-1", WorkUnitState.REJECTED)}) is False


def test_failed_dependency_is_not_ready() -> None:
    unit = work_unit(depends_on=("DEP-1",))
    assert is_ready(unit, {"DEP-1": work_unit("DEP-1", WorkUnitState.FAILED)}) is False


def test_unresolved_dependency_is_not_ready() -> None:
    unit = work_unit(depends_on=("MISSING",))
    assert is_ready(unit, {}) is False


def test_dependency_mapping_requires_matching_work_unit_identity() -> None:
    unit = work_unit(depends_on=("DEP-1",))
    dependencies = {"DEP-1": work_unit("OTHER", WorkUnitState.APPROVED)}
    assert is_ready(unit, dependencies) is False


def test_dependency_mapping_requires_matching_identity_and_approval() -> None:
    unit = work_unit(depends_on=("DEP-1",))
    dependencies = {"DEP-1": work_unit("DEP-1", WorkUnitState.PENDING)}
    assert is_ready(unit, dependencies) is False


def test_non_pending_work_unit_is_not_new_ready_candidate() -> None:
    for state in WorkUnitState:
        if state is not WorkUnitState.PENDING:
            assert is_ready(work_unit(state=state), {}) is False


def test_dependency_snapshot_does_not_replace_current_approval_gate() -> None:
    unit = WorkUnit(
        id="WU-001",
        title="Work",
        required_capability=capability("capability.work", "Work Capability"),
        depends_on=("DEP-1",),
        depends_on_snapshot=(),
    )
    assert is_ready(unit, {}) is False


def test_exact_required_capability_id_is_eligible() -> None:
    unit = work_unit()
    worker_capabilities = [capability("capability.work", "Different Name")]
    assert is_worker_eligible(unit, worker_capabilities) is True


def test_invalid_empty_required_capability_id_is_not_eligible() -> None:
    unit = work_unit(required_capability_id="")
    assert is_worker_eligible(unit, [capability("", "Work Capability")]) is False


def test_invalid_whitespace_required_capability_id_is_not_eligible() -> None:
    unit = work_unit(required_capability_id=" ")
    assert is_worker_eligible(unit, [capability(" ", "Work Capability")]) is False


def test_invalid_empty_worker_capability_id_is_not_eligible() -> None:
    unit = work_unit()
    assert is_worker_eligible(unit, [capability("", "Work Capability")]) is False


def test_invalid_whitespace_worker_capability_id_is_not_eligible() -> None:
    unit = work_unit()
    assert is_worker_eligible(unit, [capability(" ", "Work Capability")]) is False


def test_missing_capability_id_is_not_eligible() -> None:
    unit = work_unit()
    assert is_worker_eligible(unit, [capability("capability.other", "Other Capability")]) is False


def test_similar_name_does_not_match() -> None:
    unit = work_unit()
    assert is_worker_eligible(unit, [capability("capability.worker", "Work Capability")]) is False


def test_agent_registry_capability_type_is_not_accepted() -> None:
    unit = work_unit()
    registry_capability = RegistryCapability.create("capability.work", AgentVersion(1, 0, 0))
    assert is_worker_eligible(unit, [registry_capability]) is False  # type: ignore[list-item]


def test_evaluation_does_not_mutate_inputs() -> None:
    unit = work_unit(depends_on=("DEP-1",))
    dependency = work_unit("DEP-1", WorkUnitState.APPROVED)
    capabilities = [capability("capability.work", "Work Capability")]
    original_state = unit.state
    original_dependencies = unit.depends_on
    original_capabilities = list(capabilities)

    assert is_ready(unit, [dependency]) is True
    assert is_worker_eligible(unit, capabilities) is True
    assert unit.state is original_state
    assert unit.depends_on == original_dependencies
    assert capabilities == original_capabilities
