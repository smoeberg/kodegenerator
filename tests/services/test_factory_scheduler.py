from domain.factory_work import (
    ExecutionMode,
    WorkPackage,
    WorkPackageStatus,
    WriteScope,
)
from services.factory_scheduler import FactoryScheduler


class Queue:
    organization_id = "org-1"
    calls = []

    def publish(self, topic, payload, message_id=None):
        self.calls.append((topic, payload, message_id))
        return message_id


def test_scheduler_publishes_only_identity_payload() -> None:
    package = WorkPackage(
        organization_id="org-1",
        work_package_id="a" * 64,
        logical_task_id="task",
        workflow_id="workflow",
        requirements_fingerprint="b" * 64,
        architecture_fingerprint="c" * 64,
        contract_fingerprint="d" * 64,
        base_sha="e" * 40,
        dependency_ids=(),
        criterion_ids=("ac",),
        required_checks=("pytest",),
        write_scope=WriteScope(("src",)),
        execution_mode=ExecutionMode.SINGLE,
        candidate_count=1,
        allocation_id="pool",
        allocation_version=1,
        policy_fingerprint="f" * 64,
        token_budget=10,
        time_budget_seconds=10,
        idempotency_key="key",
        status=WorkPackageStatus.READY,
    )
    queue = Queue()
    FactoryScheduler(queue).publish(package)
    assert queue.calls[-1][0] == "factory.work"
    assert set(queue.calls[-1][1]) == {
        "organization_id",
        "work_package_id",
        "fingerprint",
    }
