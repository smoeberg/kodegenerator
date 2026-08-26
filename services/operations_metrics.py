"""OperationsMetrics — aggregate swarm ops state for REST and Prometheus.

Collects queue depth, worker activity, DLQ size, circuit-breaker state,
performance profiles, and cost-optimizer signals into a single snapshot
suitable for ops dashboards.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Mapping


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


@dataclass
class OperationsMetrics:
    """In-process ops metrics aggregator.

    Production can inject live adapters via ``bind_*`` methods; defaults
    use safe demo fixtures so endpoints and tests work without a full
    swarm runtime.
    """

    _lock: threading.RLock = field(default_factory=threading.RLock, repr=False)
    _queue_depth: dict[str, int] = field(
        default_factory=lambda: {
            "pending": 12,
            "claimed": 4,
            "running": 6,
            "completed": 40,
            "failed": 2,
        }
    )
    _queue_by_capability: dict[str, int] = field(
        default_factory=lambda: {
            "domain": 3,
            "code": 8,
            "test": 5,
            "security": 2,
            "arch": 1,
        }
    )
    _active_workers: int = 6
    _workers_total: int = 10
    _dlq_size: int = 2
    _circuit_breakers: dict[str, str] = field(
        default_factory=lambda: {
            "gatekeeper": "closed",
            "sandbox": "closed",
            "external_llm": "half_open",
            "artifact_store": "closed",
        }
    )
    _performance: dict[str, float] = field(
        default_factory=lambda: {
            "avg_task_seconds": 42.5,
            "p95_task_seconds": 120.0,
            "throughput_tasks_per_min": 3.2,
            "claim_latency_ms": 18.0,
        }
    )
    _cost: dict[str, float] = field(
        default_factory=lambda: {
            "tokens_used_total": 125000.0,
            "estimated_usd": 4.75,
            "budget_usd": 50.0,
            "budget_remaining_usd": 45.25,
        }
    )
    _component_health: dict[str, str] = field(
        default_factory=lambda: {
            "queue": "ok",
            "workers": "ok",
            "gatekeeper": "ok",
            "sentinel": "ok",
            "healer": "ok",
            "dlq": "degraded",
            "circuit_breakers": "ok",
            "cost_optimizer": "ok",
        }
    )

    # ------------------------------------------------------------------
    # Binders (optional live data)
    # ------------------------------------------------------------------

    def bind_queue_depth(self, depth: Mapping[str, int]) -> None:
        with self._lock:
            self._queue_depth = dict(depth)

    def bind_queue_by_capability(self, depth: Mapping[str, int]) -> None:
        with self._lock:
            self._queue_by_capability = dict(depth)

    def bind_workers(self, active: int, total: int) -> None:
        with self._lock:
            self._active_workers = int(active)
            self._workers_total = int(total)

    def bind_dlq_size(self, size: int) -> None:
        with self._lock:
            self._dlq_size = int(size)

    def bind_circuit_breakers(self, states: Mapping[str, str]) -> None:
        with self._lock:
            self._circuit_breakers = dict(states)

    def bind_performance(self, profile: Mapping[str, float]) -> None:
        with self._lock:
            self._performance = {k: float(v) for k, v in profile.items()}

    def bind_cost(self, data: Mapping[str, float]) -> None:
        with self._lock:
            self._cost = {k: float(v) for k, v in data.items()}

    def bind_component_health(self, health: Mapping[str, str]) -> None:
        with self._lock:
            self._component_health = dict(health)

    # ------------------------------------------------------------------
    # Snapshot / Prometheus
    # ------------------------------------------------------------------

    def snapshot(self) -> dict[str, Any]:
        """Complete ops state snapshot (JSON-serializable)."""
        with self._lock:
            overall = "ok"
            if any(v == "down" for v in self._component_health.values()):
                overall = "down"
            elif any(v in ("degraded", "warn") for v in self._component_health.values()):
                overall = "degraded"
            return {
                "captured_at": _utc_now_iso(),
                "status": overall,
                "queue": {
                    "depth_by_status": dict(self._queue_depth),
                    "depth_by_capability": dict(self._queue_by_capability),
                    "total_open": sum(
                        self._queue_depth.get(s, 0)
                        for s in ("pending", "claimed", "running")
                    ),
                },
                "workers": {
                    "active": self._active_workers,
                    "total": self._workers_total,
                },
                "dlq": {"size": self._dlq_size},
                "circuit_breakers": dict(self._circuit_breakers),
                "performance": dict(self._performance),
                "cost": dict(self._cost),
                "components": dict(self._component_health),
            }

    def health(self) -> dict[str, Any]:
        """Lightweight health document for /ops/health."""
        snap = self.snapshot()
        return {
            "status": snap["status"],
            "components": dict(snap["components"]),
            "captured_at": snap["captured_at"],
        }

    def prometheus_metrics(self) -> str:
        """Prometheus text exposition format."""
        lines: list[str] = []
        with self._lock:
            lines.append("# HELP swarm_queue_depth Tasks in queue by status")
            lines.append("# TYPE swarm_queue_depth gauge")
            for status, value in sorted(self._queue_depth.items()):
                lines.append(f'swarm_queue_depth{{status="{status}"}} {int(value)}')

            lines.append("# HELP swarm_queue_depth_by_capability Queue depth by required capability")
            lines.append("# TYPE swarm_queue_depth_by_capability gauge")
            for cap, value in sorted(self._queue_by_capability.items()):
                lines.append(
                    f'swarm_queue_depth_by_capability{{capability="{cap}"}} {int(value)}'
                )

            lines.append("# HELP swarm_workers_active Number of busy workers")
            lines.append("# TYPE swarm_workers_active gauge")
            lines.append(f"swarm_workers_active {int(self._active_workers)}")

            lines.append("# HELP swarm_workers_total Configured worker slots")
            lines.append("# TYPE swarm_workers_total gauge")
            lines.append(f"swarm_workers_total {int(self._workers_total)}")

            lines.append("# HELP swarm_dlq_size Dead-letter queue size")
            lines.append("# TYPE swarm_dlq_size gauge")
            lines.append(f"swarm_dlq_size {int(self._dlq_size)}")

            lines.append("# HELP swarm_circuit_breaker Circuit breaker state (0=closed 1=half_open 2=open)")
            lines.append("# TYPE swarm_circuit_breaker gauge")
            state_map = {"closed": 0, "half_open": 1, "open": 2}
            for name, state in sorted(self._circuit_breakers.items()):
                num = state_map.get(state.lower(), -1)
                lines.append(f'swarm_circuit_breaker{{name="{name}",state="{state}"}} {num}')

            lines.append("# HELP swarm_task_duration_seconds Task duration statistics")
            lines.append("# TYPE swarm_task_duration_seconds gauge")
            if "avg_task_seconds" in self._performance:
                lines.append(
                    f'swarm_task_duration_seconds{{quantile="avg"}} {self._performance["avg_task_seconds"]}'
                )
            if "p95_task_seconds" in self._performance:
                lines.append(
                    f'swarm_task_duration_seconds{{quantile="0.95"}} {self._performance["p95_task_seconds"]}'
                )

            lines.append("# HELP swarm_throughput_tasks_per_min Completed tasks per minute")
            lines.append("# TYPE swarm_throughput_tasks_per_min gauge")
            lines.append(
                f"swarm_throughput_tasks_per_min {self._performance.get('throughput_tasks_per_min', 0.0)}"
            )

            lines.append("# HELP swarm_cost_usd Estimated spend")
            lines.append("# TYPE swarm_cost_usd gauge")
            lines.append(f'swarm_cost_usd{{kind="estimated"}} {self._cost.get("estimated_usd", 0.0)}')
            lines.append(f'swarm_cost_usd{{kind="budget"}} {self._cost.get("budget_usd", 0.0)}')
            lines.append(
                f'swarm_cost_usd{{kind="remaining"}} {self._cost.get("budget_remaining_usd", 0.0)}'
            )

            lines.append("# HELP swarm_tokens_used_total LLM tokens consumed")
            lines.append("# TYPE swarm_tokens_used_total counter")
            lines.append(f"swarm_tokens_used_total {self._cost.get('tokens_used_total', 0.0)}")

        return "\n".join(lines) + "\n"


# Process-wide singleton used by the API layer.
default_operations_metrics = OperationsMetrics()
