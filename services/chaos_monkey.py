"""Synthetic chaos scenarios and invariant verification for the swarm.

All scenarios are simulated at the service boundary; this module never
executes destructive host or infrastructure commands. Integrations are
injected so production adapters can connect the governor, DR manager, and
enterprise audit implementation without coupling this harness to storage.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Mapping, Optional, Protocol
import time


class ChaosMode(str, Enum):
    """Execution mode for a chaos run."""
    DRY_RUN = "dry-run"
    INJECT = "inject"
    VERIFY = "verify"


class ChaosScenario(str, Enum):
    """Supported simulated failure scenarios."""
    KILL_WORKER = "kill-worker"
    CORRUPT_PATCH = "corrupt-patch"
    REDIS_FLUSH = "redis-flush"
    DISK_FULL = "disk-full"
    TIMEOUT = "timeout"
    DUPLICATE_COMPLETION = "duplicate-completion"


@dataclass(frozen=True)
class ChaosResult:
    """Outcome of one scenario execution."""
    scenario: ChaosScenario
    mode: ChaosMode
    injected: bool
    recovered: bool
    invariant_ok: bool
    detail: str


@dataclass(frozen=True)
class ChaosReport:
    """Immutable report for a complete chaos run."""
    run_id: str
    mode: ChaosMode
    results: tuple[ChaosResult, ...]
    started_at: float
    completed_at: float


class ChaosTarget(Protocol):
    """Optional adapter for simulating swarm-side faults."""

    def inject(self, scenario: ChaosScenario, context: Mapping[str, Any]) -> None:
        """Inject one simulated scenario."""

    def verify(self, scenario: ChaosScenario, context: Mapping[str, Any]) -> bool:
        """Verify recovery/invariants for one scenario."""


class ChaosMonkey:
    """Plan, inject, and verify safe synthetic swarm failures."""

    def __init__(
        self,
        *,
        target: Optional[ChaosTarget] = None,
        governor: Optional[Any] = None,
        dr_manager: Optional[Any] = None,
        audit: Optional[Any] = None,
        clock: Callable[[], float] = time.time,
    ) -> None:
        """Initialize the harness with dependency-injected integrations."""
        self._target = target
        self._governor = governor
        self._dr_manager = dr_manager
        self._audit = audit
        self._clock = clock

    def scenarios(self) -> tuple[ChaosScenario, ...]:
        """Return the complete supported scenario catalogue."""
        return tuple(ChaosScenario)

    def run(
        self,
        run_id: str,
        mode: ChaosMode,
        *,
        scenarios: Optional[list[ChaosScenario]] = None,
        context: Optional[Mapping[str, Any]] = None,
    ) -> ChaosReport:
        """Execute or verify selected scenarios and return a deterministic report."""
        if not run_id.strip():
            raise ValueError("run_id is required")
        selected = tuple(scenarios or list(ChaosScenario))
        ctx = dict(context or {})
        started = self._clock()
        results: list[ChaosResult] = []
        for scenario in selected:
            injected = False
            recovered = False
            detail = "planned"
            if mode == ChaosMode.DRY_RUN:
                detail = "scenario planned; no mutation performed"
            elif mode == ChaosMode.INJECT:
                if self._target is None:
                    raise RuntimeError("inject mode requires a ChaosTarget")
                self._target.inject(scenario, ctx)
                injected = True
                recovered = self._verify(scenario, ctx)
                detail = "injected and recovery verified" if recovered else "injected; recovery not verified"
            elif mode == ChaosMode.VERIFY:
                recovered = self._verify(scenario, ctx)
                detail = "invariants verified" if recovered else "invariant verification failed"
            else:
                raise ValueError(f"unsupported mode: {mode}")
            results.append(ChaosResult(scenario, mode, injected, recovered, recovered or mode == ChaosMode.DRY_RUN, detail))
            self._audit_event(run_id, scenario, mode, results[-1].invariant_ok)
        return ChaosReport(run_id, mode, tuple(results), started, self._clock())

    def _verify(self, scenario: ChaosScenario, context: Mapping[str, Any]) -> bool:
        if self._target is not None and not self._target.verify(scenario, context):
            return False
        capability = context.get("capability")
        if capability and self._governor is not None:
            if hasattr(self._governor, "dispatch_allowed") and not self._governor.dispatch_allowed(str(capability)):
                return False
        return self._drill_if_available()

    def _drill_if_available(self) -> bool:
        if self._dr_manager is None or not hasattr(self._dr_manager, "drill"):
            return True
        return bool(self._dr_manager.drill())

    def _audit_event(self, run_id: str, scenario: ChaosScenario, mode: ChaosMode, ok: bool) -> None:
        if self._audit is None:
            return
        action = f"chaos.{scenario.value}"
        if hasattr(self._audit, "append"):
            self._audit.append(actor="chaos-monkey", action=action, resource=run_id, outcome="success" if ok else "failure", timestamp=self._clock())
        elif hasattr(self._audit, "record"):
            self._audit.record(actor="chaos-monkey", action=action, resource=run_id, outcome="success" if ok else "failure", timestamp=self._clock())
