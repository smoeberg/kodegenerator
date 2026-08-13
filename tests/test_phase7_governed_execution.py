from domain.task_execution import ExecutionResult, TaskExecutionStatus
from infrastructure.runtime.governed_execution import GovernedExecutionHandler


class FakeService:
    def __init__(self):
        self.calls = []

    def execute(self, principal, request):
        self.calls.append((principal, request))
        return ExecutionResult(
            execution_id=request.execution_id,
            status=TaskExecutionStatus.SUCCEEDED,
            result={"ok": True},
        )


def test_worker_handler_reconstructs_canonical_request_and_principal():
    service = FakeService()
    handler = GovernedExecutionHandler(lambda: service)

    result = handler(
        {
            "execution_id": "exec-1",
            "organization_id": "org-1",
            "actor_id": "actor-1",
            "task_type": "compile",
            "capability_id": "compile",
            "payload": {"source": "x"},
        }
    )

    principal, request = service.calls[0]
    assert principal.id == "actor-1"
    assert principal.type == "service"
    assert request.execution_id == "exec-1"
    assert request.organization_id == "org-1"
    assert request.payload == {"source": "x"}
    assert result["status"] == "succeeded"
    assert result["result"] == {"ok": True}
