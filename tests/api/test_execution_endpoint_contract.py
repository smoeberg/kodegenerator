"""Contract tests for the Development & Execution control-plane API."""

from api.endpoints.execution import (
    AdvanceExecutionRequest,
    GateDecisionRequest,
    ImplementationProposalRequest,
    StartExecutionRequest,
    _websocket_token,
    router,
)


def test_execution_router_exposes_canonical_http_and_realtime_contract() -> None:
    routes = {(route.path, frozenset(getattr(route, "methods", ()) or ())) for route in router.routes}

    assert ("/api/v1/execution/{workflow_id}", frozenset({"GET"})) in routes
    assert ("/api/v1/execution/start", frozenset({"POST"})) in routes
    assert ("/api/v1/execution/{workflow_id}/advance", frozenset({"POST"})) in routes
    assert ("/api/v1/execution/{workflow_id}/gates", frozenset({"GET"})) in routes
    assert ("/api/v1/execution/{workflow_id}/gates/decide", frozenset({"POST"})) in routes
    assert ("/api/v1/execution/{workflow_id}/proposals", frozenset({"GET"})) in routes
    assert ("/api/v1/execution/{workflow_id}/proposals", frozenset({"POST"})) in routes
    assert any(
        route.path == "/api/v1/execution/ws/{workflow_id}"
        for route in router.routes
    )
    assert ("/api/v1/execution/events/{workflow_id}", frozenset({"GET"})) in routes


def test_execution_request_models_are_fail_closed_on_extra_fields() -> None:
    start = StartExecutionRequest(
        requirements_yaml="version: 1\n",
        organization_id="org-1",
    )
    assert start.organization_id == "org-1"

    advance = AdvanceExecutionRequest(reason="manual review")
    assert advance.reason == "manual review"

    gate = GateDecisionRequest(gate_id="gate-1", decision="rejected")
    assert gate.decision == "rejected"

    proposal = ImplementationProposalRequest(
        title="Use staged rollout",
        summary="Reduce deployment blast radius.",
        files=[{"path": "deploy.yaml", "reason": "stage rollout"}],
    )
    assert proposal.files[0]["path"] == "deploy.yaml"

    for model, payload in (
        (StartExecutionRequest, {"requirements_yaml": "x", "organization_id": "o", "extra": 1}),
        (AdvanceExecutionRequest, {"reason": "x", "extra": 1}),
        (GateDecisionRequest, {"gate_id": "g", "decision": "approved", "extra": 1}),
        (ImplementationProposalRequest, {"title": "t", "summary": "s", "extra": 1}),
    ):
        try:
            model.model_validate(payload)
        except ValueError:
            continue
        raise AssertionError(f"{model.__name__} accepted an unexpected field")


def test_execution_gate_decision_model_only_accepts_supported_decisions() -> None:
    for decision in ("approved", "rejected"):
        assert GateDecisionRequest(gate_id="gate-1", decision=decision).decision == decision

    try:
        GateDecisionRequest(gate_id="gate-1", decision="pending")
    except ValueError:
        pass
    else:
        raise AssertionError("GateDecisionRequest accepted unsupported decision")


def test_websocket_token_parser_requires_bearer_scheme() -> None:
    class Headers(dict):
        def get(self, key, default=None):
            return super().get(key.lower(), default)

    class Socket:
        def __init__(self, authorization: str):
            self.headers = Headers({"authorization": authorization})

    assert _websocket_token(Socket("Bearer abc123")) == "abc123"
    assert _websocket_token(Socket("bearer abc123")) == "abc123"
    assert _websocket_token(Socket("Basic abc123")) is None
    assert _websocket_token(Socket("Bearer")) is None
    assert _websocket_token(Socket("")) is None
