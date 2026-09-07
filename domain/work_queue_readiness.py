"""Deterministic, side-effect-free Work Queue v0 readiness rules."""

from __future__ import annotations

from collections.abc import Iterable, Mapping

from .capability import Capability
from .work_queue import WorkUnit, WorkUnitState


def _valid_capability_id(value: object) -> bool:
    """Return whether a capability ID has the minimal v0 canonical shape."""
    return isinstance(value, str) and bool(value.strip())


def is_ready(work_unit: WorkUnit, dependencies: Mapping[str, WorkUnit] | Iterable[WorkUnit]) -> bool:
    """Return whether a WorkUnit is a READY candidate under the v0 rule."""
    if not isinstance(work_unit, WorkUnit) or work_unit.state is not WorkUnitState.PENDING:
        return False

    dependency_map = dependencies if isinstance(dependencies, Mapping) else {d.id: d for d in dependencies}
    return all(
        isinstance(dependency_map.get(dep_id), WorkUnit)
        and dependency_map[dep_id].id == dep_id
        and dependency_map[dep_id].state is WorkUnitState.APPROVED
        for dep_id in work_unit.depends_on
    )


def is_worker_eligible(work_unit: WorkUnit, worker_capabilities: Iterable[Capability]) -> bool:
    """Return whether worker capabilities contain the required DOR Capability ID."""
    if not isinstance(work_unit, WorkUnit) or not isinstance(work_unit.required_capability, Capability):
        return False

    required_id = work_unit.required_capability.id
    if not _valid_capability_id(required_id):
        return False

    return any(
        isinstance(capability, Capability)
        and _valid_capability_id(capability.id)
        and capability.id == required_id
        for capability in worker_capabilities
    )


__all__ = ["is_ready", "is_worker_eligible"]
