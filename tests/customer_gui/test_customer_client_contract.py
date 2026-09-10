from typing import Any

import pytest

from customer_gui.client import CustomerAPI, CustomerContractError


FP = "a" * 64


class FakeClient:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, dict[str, Any]]] = []
        self.responses: dict[tuple[str, str], Any] = {}

    def login(self, username: str, password: str) -> str:
        self.calls.append(("LOGIN", username, {"password": password}))
        return "token"

    def get(self, path: str, **kwargs: Any) -> Any:
        self.calls.append(("GET", path, kwargs))
        return self.responses[("GET", path)]

    def post(self, path: str, **kwargs: Any) -> Any:
        self.calls.append(("POST", path, kwargs))
        return self.responses[("POST", path)]


def test_project_catalog_requires_exact_tenant_scope() -> None:
    fake = FakeClient()
    fake.responses[("GET", "/api/v1/control-plane/projects")] = {
        "organization_id": "org-a",
        "projects": [{"project_id": "p1", "organization_id": "org-b"}],
    }
    with pytest.raises(CustomerContractError):
        CustomerAPI(client=fake).projects("org-a")


def test_project_execution_requires_exact_case_and_plan_fingerprint() -> None:
    fake = FakeClient()
    path = "/api/v1/control-plane/projects/p1/execution"
    fake.responses[("GET", path)] = {
        "workflow_id": "wf-1",
        "project_id": "p1",
        "plan_request_fingerprint": FP,
    }
    value = CustomerAPI(client=fake).project_execution(
        {"project_id": "p1", "active_plan_request_fingerprint": FP}
    )
    assert value["workflow_id"] == "wf-1"
    assert fake.calls[-1] == (
        "GET",
        path,
        {"params": {"plan_request_fingerprint": FP}},
    )


def test_proposal_list_rejects_unrelated_workflow() -> None:
    fake = FakeClient()
    path = "/api/v1/execution/wf-1/proposals"
    fake.responses[("GET", path)] = [{"id": "proposal-1", "workflow_id": "wf-other"}]
    with pytest.raises(CustomerContractError):
        CustomerAPI(client=fake).proposals("wf-1")


def test_approve_and_reject_use_only_existing_gate_decision_command() -> None:
    fake = FakeClient()
    path = "/api/v1/execution/wf-1/gates/decide"
    fake.responses[("POST", path)] = {
        "workflow_id": "wf-1",
        "gate_id": "gate-1",
        "decision": "approved",
    }
    api = CustomerAPI(client=fake)
    api.decide("wf-1", "gate-1", "approved")
    assert fake.calls[-1] == (
        "POST",
        path,
        {"json": {"gate_id": "gate-1", "decision": "approved"}},
    )

    fake.responses[("POST", path)] = {
        "workflow_id": "wf-1",
        "gate_id": "gate-1",
        "decision": "rejected",
    }
    api.decide("wf-1", "gate-1", "rejected")
    assert fake.calls[-1][2]["json"]["decision"] == "rejected"


def test_request_changes_uses_governed_rework_only_after_reason() -> None:
    fake = FakeClient()
    path = "/api/v1/execution/wf-1/gates/rework"
    fake.responses[("POST", path)] = {"workflow_id": "wf-1", "gate_id": "gate-1"}
    api = CustomerAPI(client=fake)
    with pytest.raises(ValueError):
        api.request_changes("wf-1", "gate-1", "  ")
    api.request_changes("wf-1", "gate-1", "Ret dokumentationen")
    assert fake.calls[-1] == (
        "POST",
        path,
        {"json": {"gate_id": "gate-1", "reason": "Ret dokumentationen"}},
    )
