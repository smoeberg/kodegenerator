"""P6-06 audit invariants."""

from dataclasses import dataclass

import pytest

from phase6.execution.audit import ExecutionAuditEvent
from phase6.execution.sandbox import (
    ExecutionLimits,
    ExecutionOutcome,
    ExecutionResult,
    ExecutionSecurityContext,
    ExecutionSpec,
    SandboxRegistry,
)


@dataclass
class RecordingSink:
    events: list[ExecutionAuditEvent]

    def emit(self, event: ExecutionAuditEvent) -> None:
        self.events.append(event)


class SuccessfulAdapter:
    adapter_id = "test"

    def execute(self, spec: ExecutionSpec) -> ExecutionResult:
        return ExecutionResult(spec.execution_id, self.adapter_id, ExecutionOutcome.SUCCEEDED, output="ok", exit_code=0)


def make_spec() -> ExecutionSpec:
    return ExecutionSpec(
        execution_id="audit-1",
        adapter_id="test",
        argv=("/usr/bin/true",),
        security=ExecutionSecurityContext("org", "principal", "actor"),
        limits=ExecutionLimits(output_bytes=4096),
    )


def test_registry_emits_started_and_finished_without_payload_leakage():
    sink = RecordingSink([])
    registry = SandboxRegistry({"test": SuccessfulAdapter()}, audit_sink=sink)

    result = registry.execute(make_spec())

    assert result.outcome is ExecutionOutcome.SUCCEEDED
    assert [event.event_type for event in sink.events] == ["execution.started", "execution.finished"]
    assert sink.events[0].execution_id == "audit-1"
    assert all("/usr/bin/true" not in event.as_dict().values() for event in sink.events)


def test_audit_event_rejects_oversized_identity_fields():
    with pytest.raises(ValueError):
        ExecutionAuditEvent("execution.started", "x" * 257, "test", "started", "2026-08-10T00:00:00Z")
