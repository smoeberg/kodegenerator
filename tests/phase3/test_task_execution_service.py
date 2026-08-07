from __future__ import annotations

from dataclasses import dataclass

import pytest

from domain.actor import Actor, ActorType
from domain.event import EventType
from domain.principal import Principal
from domain.task_execution import TaskExecutionRequest, TaskExecutionStatus
from services.task_execution_service import (
    DictTaskExecutorFactory,
    ExecutionConflictError,
    TaskExecutionService,
    UnknownTaskTypeError,
)


class MemorySession:
    def commit(self) -> None:
        pass


class MemoryEvents:
    def __init__(self) -> None:
        self.items = []

    def append(self, event) -> None:
        self.items.append(event)


class MemoryExecutions:
    def __init__(self) -> None:
        self.items = {}

    def get(self, execution_id, organization_id):
        return self.items.get((execution_id, organization_id))

    def add(self, receipt):
        self.items[(receipt.execution_id, receipt.organization_id)] = receipt

    def update(self, receipt):
        self.items[(receipt.execution_id, receipt.organization_id)] = receipt


@dataclass
class MemoryAuthority:
    capabilities: set[str]

    def get_effective_capabilities(self, actor_id, organization_id):
        return set(self.capabilities)


class MemoryActors:
    def __init__(self, actor: Actor | None, organization_id: str = "org-a") -> None:
        self.actor = actor
        self.organization_id = organization_id

    def get_for_organization(self, actor_id, organization_id):
        if self.actor is None:
            return None
        if self.actor.id != actor_id or self.organization_id != organization_id:
            return None
        return self.actor


class MemoryUow:
    def __init__(self, actor: Actor | None, capabilities: set[str]):
        self.session = MemorySession()
        self.actors = MemoryActors(actor)
        self.authority = MemoryAuthority(capabilities)
        self.events = MemoryEvents()
        self.task_executions = MemoryExecutions()


class CountingExecutor:
    def __init__(self, result=None, error=None):
        self.calls = 0
        self.result = result or {"ok": True}
        self.error = error

    def execute(self, payload):
        self.calls += 1
        if self.error is not None:
            raise self.error
        return dict(self.result)


def actor(status="active"):
    return Actor(
        id="actor-1",
        type=ActorType.DIGITAL_EMPLOYEE,
        identity="employee-1",
        status=status,
    )


def principal(actor_id="actor-1"):
    return Principal(id=actor_id, type="service")


def request(**overrides):
    values = dict(
        execution_id="exec-1",
        organization_id="org-a",
        actor_id="actor-1",
        task_type="workflow.transition",
        capability_id="workflow.transition",
        payload={"target": "review"},
    )
    values.update(overrides)
    return TaskExecutionRequest(**values)


def service(*, capabilities=None, actor_status="active", executor=None, ready=True):
    uow = MemoryUow(actor(actor_status), capabilities if capabilities is not None else {"workflow.transition"})
    executor = executor or CountingExecutor()
    svc = TaskExecutionService(
        uow,
        DictTaskExecutorFactory({"workflow.transition": executor}),
        runtime_ready=ready,
    )
    return svc, uow, executor


def test_request_requires_explicit_organization():
    with pytest.raises(TypeError):
        TaskExecutionRequest(execution_id="x", actor_id="a", task_type="t", capability_id="t")


def test_resource_requires_resource_organization():
    with pytest.raises(ValueError):
        request(resource_id="r")


def test_pending_receipt_has_canonical_initial_state():
    svc, uow, _ = service()
    result = svc.execute(principal(), request())
    receipt = uow.task_executions.get("exec-1", "org-a")
    assert receipt.status is TaskExecutionStatus.SUCCEEDED
    assert result.execution_id == "exec-1"


def test_state_machine_rejects_terminal_to_running():
    svc, uow, _ = service()
    svc.execute(principal(), request())
    receipt = uow.task_executions.get("exec-1", "org-a")
    with pytest.raises(ValueError):
        receipt.transition(TaskExecutionStatus.RUNNING)


def test_runtime_not_ready_fails_closed():
    svc, _, executor = service(ready=False)
    with pytest.raises(RuntimeError):
        svc.execute(principal(), request())
    assert executor.calls == 0


def test_principal_actor_mismatch_is_denied():
    svc, _, executor = service()
    with pytest.raises(PermissionError):
        svc.execute(principal("other-actor"), request())
    assert executor.calls == 0


def test_inactive_actor_is_denied():
    svc, _, executor = service(actor_status="suspended")
    with pytest.raises(PermissionError):
        svc.execute(principal(), request())
    assert executor.calls == 0


def test_missing_capability_is_denied():
    svc, _, executor = service(capabilities=set())
    with pytest.raises(PermissionError):
        svc.execute(principal(), request())
    assert executor.calls == 0


def test_cross_organization_resource_is_denied():
    svc, _, executor = service()
    with pytest.raises(PermissionError):
        svc.execute(principal(), request(resource_id="r-1", resource_organization_id="org-b"))
    assert executor.calls == 0


def test_authorized_execution_succeeds():
    svc, _, executor = service()
    result = svc.execute(principal(), request())
    assert result.status is TaskExecutionStatus.SUCCEEDED
    assert executor.calls == 1


def test_denied_execution_never_calls_executor():
    svc, _, executor = service(capabilities=set())
    with pytest.raises(PermissionError):
        svc.execute(principal(), request())
    assert executor.calls == 0


def test_repeated_identical_execution_id_is_idempotent():
    svc, _, executor = service()
    first = svc.execute(principal(), request())
    second = svc.execute(principal(), request())
    assert first == second
    assert executor.calls == 1


def test_conflicting_execution_id_is_rejected():
    svc, _, executor = service()
    svc.execute(principal(), request())
    with pytest.raises(ExecutionConflictError):
        svc.execute(principal(), request(payload={"different": True}))
    assert executor.calls == 1


def test_executor_failure_is_persisted_without_raw_exception_text():
    secret_error = RuntimeError("provider-secret-token=do-not-persist")
    svc, uow, _ = service(executor=CountingExecutor(error=secret_error))
    result = svc.execute(principal(), request())
    receipt = uow.task_executions.get("exec-1", "org-a")
    assert result.status is TaskExecutionStatus.FAILED
    assert receipt.error_code == "execution_failed"
    assert "provider-secret-token" not in (receipt.error_message or "")


def test_unknown_task_type_is_explicitly_rejected_and_recorded():
    svc, uow, _ = service()
    with pytest.raises(UnknownTaskTypeError):
        svc.execute(principal(), request(task_type="unknown.task"))
    receipt = uow.task_executions.get("exec-1", "org-a")
    assert receipt.status is TaskExecutionStatus.FAILED
    assert receipt.error_code == "executor_not_registered"


def test_execution_events_are_organization_scoped():
    svc, uow, _ = service()
    svc.execute(principal(), request())
    execution_events = [
        event for event in uow.events.items
        if event.event_type in {EventType.EXECUTION_STARTED, EventType.EXECUTION_COMPLETED}
    ]
    assert {event.organization_id for event in execution_events} == {"org-a"}
    assert all("payload" not in event.metadata for event in execution_events)


def test_authorization_event_precedes_execution_events():
    svc, uow, _ = service()
    svc.execute(principal(), request())
    assert uow.events.items[0].event_type is EventType.AUTHORIZATION_GRANTED
    assert uow.events.items[1].event_type is EventType.EXECUTION_STARTED


def test_failed_execution_is_terminal_and_idempotent():
    svc, _, executor = service(executor=CountingExecutor(error=RuntimeError("boom")))
    first = svc.execute(principal(), request())
    second = svc.execute(principal(), request())
    assert first.status is TaskExecutionStatus.FAILED
    assert second.status is TaskExecutionStatus.FAILED
    assert executor.calls == 1
