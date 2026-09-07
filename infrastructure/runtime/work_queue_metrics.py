"""WQ-107 observational metrics for Work Queue v0.

Metrics are intentionally passive.  They never influence readiness, capability
matching, claim order, lease recovery, review decisions, or rework routing.
Queue gauges are derived from the durable WorkUnit projection; runtime timings
and rates are process-local observations supplied explicitly by callers.
"""

from __future__ import annotations

import math
import threading
from dataclasses import dataclass

from domain.work_queue import WorkUnit, WorkUnitState
from domain.work_queue_readiness import is_ready
from infrastructure.persistence.database import apply_tenant_context
from infrastructure.persistence.work_queue_repository import WorkUnitRepository


@dataclass(frozen=True)
class WorkQueueMetricsSnapshot:
    queue_depth: int
    ready_queue_depth: int
    claim_latency: float
    claim_conflict_rate: float
    worker_busy_time: float
    worker_idle_time: float
    worker_utilization: float
    execution_duration: float
    review_queue_depth: int
    review_wait_time: float
    review_duration: float
    rejection_rate: float
    rework_rate: float
    lease_expiry_count: int


class WorkQueueMetrics:
    """Thread-safe, process-local observation accumulator.

    Durations are seconds.  Latency and duration fields in a snapshot are means;
    busy/idle time and lease-expiry count are cumulative.  Empty populations
    report ``0.0`` rather than fabricating samples.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._claim_attempts = 0
        self._claim_conflicts = 0
        self._claim_latency_total = 0.0
        self._worker_busy_time = 0.0
        self._worker_idle_time = 0.0
        self._execution_count = 0
        self._execution_duration_total = 0.0
        self._review_wait_count = 0
        self._review_wait_total = 0.0
        self._review_count = 0
        self._review_rejections = 0
        self._review_duration_total = 0.0
        self._rework_count = 0
        self._lease_expiry_count = 0

    def record_claim(self, *, latency_seconds: float, conflict: bool = False) -> None:
        latency = _duration(latency_seconds, "latency_seconds")
        with self._lock:
            self._claim_attempts += 1
            self._claim_latency_total += latency
            if conflict:
                self._claim_conflicts += 1

    def record_worker_busy(self, seconds: float) -> None:
        value = _duration(seconds, "seconds")
        with self._lock:
            self._worker_busy_time += value

    def record_worker_idle(self, seconds: float) -> None:
        value = _duration(seconds, "seconds")
        with self._lock:
            self._worker_idle_time += value

    def record_execution(self, seconds: float) -> None:
        value = _duration(seconds, "seconds")
        with self._lock:
            self._execution_count += 1
            self._execution_duration_total += value

    def record_review_wait(self, seconds: float) -> None:
        value = _duration(seconds, "seconds")
        with self._lock:
            self._review_wait_count += 1
            self._review_wait_total += value

    def record_review(self, *, duration_seconds: float, rejected: bool) -> None:
        value = _duration(duration_seconds, "duration_seconds")
        with self._lock:
            self._review_count += 1
            self._review_duration_total += value
            if rejected:
                self._review_rejections += 1

    def record_rework(self) -> None:
        with self._lock:
            self._rework_count += 1

    def record_lease_expiry(self) -> None:
        with self._lock:
            self._lease_expiry_count += 1

    def _runtime_values(self) -> dict[str, float | int]:
        with self._lock:
            utilization_denominator = self._worker_busy_time + self._worker_idle_time
            return {
                "claim_latency": _mean(self._claim_latency_total, self._claim_attempts),
                "claim_conflict_rate": _rate(self._claim_conflicts, self._claim_attempts),
                "worker_busy_time": self._worker_busy_time,
                "worker_idle_time": self._worker_idle_time,
                "worker_utilization": (
                    self._worker_busy_time / utilization_denominator
                    if utilization_denominator
                    else 0.0
                ),
                "execution_duration": _mean(
                    self._execution_duration_total, self._execution_count
                ),
                "review_wait_time": _mean(
                    self._review_wait_total, self._review_wait_count
                ),
                "review_duration": _mean(
                    self._review_duration_total, self._review_count
                ),
                "rejection_rate": _rate(self._review_rejections, self._review_count),
                "rework_rate": _rate(self._rework_count, self._review_rejections),
                "lease_expiry_count": self._lease_expiry_count,
            }


class WorkQueueMetricsService:
    """Combine durable queue gauges with passive process-local observations."""

    _QUEUED_STATES = frozenset(
        {
            WorkUnitState.PENDING,
            WorkUnitState.CLAIMED,
            WorkUnitState.AWAITING_REVIEW,
            WorkUnitState.REJECTED,
        }
    )

    def __init__(self, session_factory, *, organization_id: str, metrics: WorkQueueMetrics | None = None) -> None:
        if not isinstance(organization_id, str):
            raise ValueError("organization_id must be text")
        organization_id = organization_id.strip()
        if not organization_id or len(organization_id) > 128:
            raise ValueError("organization_id must contain 1-128 characters")
        self.session_factory = session_factory
        self.organization_id = organization_id
        self.metrics = metrics or WorkQueueMetrics()

    def snapshot(self) -> WorkQueueMetricsSnapshot:
        with self.session_factory() as session:
            apply_tenant_context(session, self.organization_id)
            work_units = WorkUnitRepository(session).list_for_organization(self.organization_id)

        by_id = {work_unit.id: work_unit for work_unit in work_units}
        queue_depth = sum(work_unit.state in self._QUEUED_STATES for work_unit in work_units)
        ready_queue_depth = sum(
            self._claimably_ready(work_unit, by_id) for work_unit in work_units
        )
        review_queue_depth = sum(
            work_unit.state is WorkUnitState.AWAITING_REVIEW for work_unit in work_units
        )
        runtime = self.metrics._runtime_values()
        return WorkQueueMetricsSnapshot(
            queue_depth=queue_depth,
            ready_queue_depth=ready_queue_depth,
            review_queue_depth=review_queue_depth,
            **runtime,
        )

    @staticmethod
    def _claimably_ready(work_unit: WorkUnit, by_id: dict[str, WorkUnit]) -> bool:
        if not is_ready(work_unit, by_id):
            return False
        return all(
            by_id[dependency_id].delivered_artifact_version is not None
            for dependency_id in work_unit.depends_on
        )


def _duration(value: float, field_name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{field_name} must be numeric")
    value = float(value)
    if value < 0 or not math.isfinite(value):
        raise ValueError(f"{field_name} must be finite and non-negative")
    return value


def _mean(total: float, count: int) -> float:
    return total / count if count else 0.0


def _rate(numerator: int, denominator: int) -> float:
    return numerator / denominator if denominator else 0.0


__all__ = ["WorkQueueMetrics", "WorkQueueMetricsService", "WorkQueueMetricsSnapshot"]
