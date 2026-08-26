"""End-to-end tests for the synthetic chaos harness."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from services.chaos_monkey import ChaosMode, ChaosMonkey, ChaosScenario


@dataclass
class FakeTarget:
    injected: list[ChaosScenario]
    healthy: bool = True

    def inject(self, scenario: ChaosScenario, context: Mapping[str, Any]) -> None:
        self.injected.append(scenario)

    def verify(self, scenario: ChaosScenario, context: Mapping[str, Any]) -> bool:
        return self.healthy


class FakeGovernor:
    def __init__(self, allowed: bool = True) -> None:
        self.allowed = allowed

    def dispatch_allowed(self, capability: str) -> bool:
        return self.allowed


class FakeDR:
    def __init__(self, result: bool = True) -> None:
        self.result = result

    def drill(self) -> bool:
        return self.result


def test_dry_run_plans_without_injection() -> None:
    target = FakeTarget([])
    monkey = ChaosMonkey(target=target)
    report = monkey.run("run-1", ChaosMode.DRY_RUN, scenarios=[ChaosScenario.KILL_WORKER])
    assert target.injected == []
    assert report.results[0].invariant_ok
    assert not report.results[0].injected


def test_inject_verifies_recovery_and_dr() -> None:
    target = FakeTarget([])
    monkey = ChaosMonkey(target=target, governor=FakeGovernor(), dr_manager=FakeDR())
    report = monkey.run("run-2", ChaosMode.INJECT, scenarios=[ChaosScenario.CORRUPT_PATCH], context={"capability": "domain"})
    assert target.injected == [ChaosScenario.CORRUPT_PATCH]
    assert report.results[0].invariant_ok
    assert report.results[0].recovered


def test_failed_invariant_is_reported() -> None:
    target = FakeTarget([], healthy=False)
    monkey = ChaosMonkey(target=target, dr_manager=FakeDR())
    report = monkey.run("run-3", ChaosMode.INJECT, scenarios=[ChaosScenario.DISK_FULL])
    assert not report.results[0].invariant_ok
    assert not report.results[0].recovered


def test_verify_mode_does_not_inject() -> None:
    target = FakeTarget([])
    monkey = ChaosMonkey(target=target)
    report = monkey.run("run-4", ChaosMode.VERIFY, scenarios=[ChaosScenario.TIMEOUT, ChaosScenario.DUPLICATE_COMPLETION])
    assert target.injected == []
    assert all(result.invariant_ok for result in report.results)


def test_governor_can_block_recovery_verification() -> None:
    target = FakeTarget([])
    monkey = ChaosMonkey(target=target, governor=FakeGovernor(allowed=False))
    report = monkey.run("run-5", ChaosMode.INJECT, scenarios=[ChaosScenario.REDIS_FLUSH], context={"capability": "security"})
    assert target.injected == [ChaosScenario.REDIS_FLUSH]
    assert not report.results[0].invariant_ok
