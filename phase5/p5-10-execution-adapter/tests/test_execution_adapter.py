"""P5-10 execution adapter contract tests.

These tests intentionally target the public P5-10 API before implementation.
"""

from dataclasses import FrozenInstanceError
import importlib.util
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[2]
P509_PATH = ROOT / "p5-09-execution-boundary" / "execution_boundary.py"
spec = importlib.util.spec_from_file_location("p509_execution_boundary", P509_PATH)
p509 = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = p509
assert spec.loader is not None
spec.loader.exec_module(p509)

ExecutionRequest = p509.ExecutionRequest
ExecutionKind = p509.ExecutionKind

# P5 directories use hyphens; load the not-yet-existing P5-10 module by path.
P510_PATH = ROOT / "p5-10-execution-adapter" / "execution_adapter.py"
p510_spec = importlib.util.spec_from_file_location("p510_execution_adapter", P510_PATH)
p510 = importlib.util.module_from_spec(p510_spec)
sys.modules[p510_spec.name] = p510
assert p510_spec.loader is not None
p510_spec.loader.exec_module(p510)

ExecutionAdapter = p510.ExecutionAdapter
AdapterPolicy = p510.AdapterPolicy
ExecutionResult = p510.ExecutionResult


class FakeAdapter:
    supported_kinds = {ExecutionKind.RETRY, ExecutionKind.ESCALATION}

    def __init__(self, outcome="success"):
        self.calls = []
        self.outcome = outcome

    def execute(self, request):
        self.calls.append(request)
        if self.outcome == "failure":
            raise RuntimeError("adapter failed")
        return {"status": "accepted"}


def request(kind=ExecutionKind.RETRY):
    return ExecutionRequest(
        request_id="req-001",
        resolution_id="res-001",
        resolution_fingerprint="rfp-001",
        disposition="RETRY_REQUESTED" if kind is ExecutionKind.RETRY else "ESCALATION_REQUIRED",
        execution_kind=kind,
        adapter_id="adapter-001",
    )


def test_authorized_supported_request_invokes_adapter_once():
    adapter = FakeAdapter()
    policy = AdapterPolicy(adapter_id="adapter-001", authorized=True)
    result = ExecutionAdapter().execute(request(), policy, adapter)
    assert isinstance(result, ExecutionResult)
    assert len(adapter.calls) == 1
    assert adapter.calls[0].request_id == "req-001"


def test_missing_adapter_fails_closed_without_invocation():
    policy = AdapterPolicy(adapter_id="adapter-001", authorized=True)
    with pytest.raises(ValueError):
        ExecutionAdapter().execute(request(), policy, None)


def test_unauthorized_adapter_fails_closed():
    adapter = FakeAdapter()
    policy = AdapterPolicy(adapter_id="adapter-001", authorized=False)
    with pytest.raises(PermissionError):
        ExecutionAdapter().execute(request(), policy, adapter)
    assert adapter.calls == []


def test_adapter_identity_must_match_request():
    adapter = FakeAdapter()
    policy = AdapterPolicy(adapter_id="different-adapter", authorized=True)
    with pytest.raises(PermissionError):
        ExecutionAdapter().execute(request(), policy, adapter)
    assert adapter.calls == []


def test_unsupported_execution_kind_fails_closed():
    adapter = FakeAdapter()
    adapter.supported_kinds = set()
    policy = AdapterPolicy(adapter_id="adapter-001", authorized=True)
    with pytest.raises(ValueError):
        ExecutionAdapter().execute(request(), policy, adapter)
    assert adapter.calls == []


def test_request_is_passed_without_reinterpretation():
    adapter = FakeAdapter()
    policy = AdapterPolicy(adapter_id="adapter-001", authorized=True)
    original = request()
    ExecutionAdapter().execute(original, policy, adapter)
    assert adapter.calls[0] == original


def test_adapter_is_invoked_exactly_once():
    adapter = FakeAdapter()
    policy = AdapterPolicy(adapter_id="adapter-001", authorized=True)
    ExecutionAdapter().execute(request(), policy, adapter)
    assert len(adapter.calls) == 1


def test_adapter_failure_is_not_converted_to_success():
    adapter = FakeAdapter(outcome="failure")
    policy = AdapterPolicy(adapter_id="adapter-001", authorized=True)
    with pytest.raises(RuntimeError):
        ExecutionAdapter().execute(request(), policy, adapter)
    assert len(adapter.calls) == 1


def test_execution_result_is_immutable():
    adapter = FakeAdapter()
    policy = AdapterPolicy(adapter_id="adapter-001", authorized=True)
    result = ExecutionAdapter().execute(request(), policy, adapter)
    with pytest.raises((FrozenInstanceError, TypeError, AttributeError)):
        result.request_id = "changed"


def test_result_preserves_request_identity():
    adapter = FakeAdapter()
    policy = AdapterPolicy(adapter_id="adapter-001", authorized=True)
    result = ExecutionAdapter().execute(request(), policy, adapter)
    assert result.request_id == "req-001"
    assert result.resolution_id == "res-001"
    assert result.resolution_fingerprint == "rfp-001"
