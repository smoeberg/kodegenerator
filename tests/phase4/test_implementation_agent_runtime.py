"""Operational tests for the governed Implementation Agent runtime/provider."""

from __future__ import annotations

import json
import urllib.request

import pytest

from phase4.context_packet import ContextItem, ContextPacketEngine, ContextRequest
from phase4.execution import ExecutionStatus
from phase4.implementation_agent import (
    IMPLEMENTATION_ACTION,
    OPENAI_IMPLEMENTATION_RESPONSES_URL,
    ChangeBudget,
    ImplementationAgentAuthorityError,
    ImplementationAgentExecutionError,
    ImplementationAgentRuntime,
    ImplementationCommandConflictError,
    ImplementationContextLimitError,
    ImplementationRequest,
    OpenAIImplementationInputLimitError,
    OpenAIImplementationProvider,
    OpenAIImplementationProviderError,
    OpenAIImplementationResponseError,
    PatchCandidate,
)
from phase4.implementation_agent.openai_provider import _http_transport
from phase4.outcome.models import OutcomeStatus

RESOURCE = "repository:smoeberg/kodegenerator"
ORGANIZATION_ID = "org:implementation-runtime-tests"
VALID_DIFF = """diff --git a/src/app.py b/src/app.py
--- a/src/app.py
+++ b/src/app.py
@@ -1 +1 @@
-VALUE = 1
+VALUE = 2
"""


class StaticImplementationProvider:
    provider_id = "fake.runtime"

    def __init__(self, unified_diff: str = VALID_DIFF) -> None:
        self.unified_diff = unified_diff
        self.calls: list[str] = []

    def propose_patch(self, request: ImplementationRequest) -> PatchCandidate:
        self.calls.append(request.request_fingerprint)
        return PatchCandidate(self.unified_diff)


def _items(value: str = "VALUE = 1\n") -> tuple[ContextItem, ...]:
    return (
        ContextItem(source="repository", key="src/app.py", value=value, provenance="git:abc123:src/app.py"),
        ContextItem(source="requirements", key="acceptance", value="VALUE must equal 2", provenance="requirement:REQ-1"),
    )


def _run(runtime: ImplementationAgentRuntime, **overrides):
    values = {
        "resource": RESOURCE,
        "instruction": "Set VALUE to 2.",
        "allowed_paths": ("src/app.py",),
        "context_items": _items(),
        "budget": ChangeBudget(max_files=1, max_changed_lines=2),
        "idempotency_key": "command-1",
        "organization_id": ORGANIZATION_ID,
    }
    values.update(overrides)
    return runtime.run(**values)


def _request() -> ImplementationRequest:
    packet = ContextPacketEngine().build(
        ContextRequest(agent_identity="agent.implementation", purpose=IMPLEMENTATION_ACTION),
        _items(),
    )
    return ImplementationRequest(
        agent_identity="agent.implementation",
        agent_role="executor",
        resource=RESOURCE,
        context_packet=packet,
        instruction="Set VALUE to 2.",
        allowed_paths=("src/app.py",),
        budget=ChangeBudget(max_files=1, max_changed_lines=2),
        organization_id=ORGANIZATION_ID,
    )


def test_runtime_executes_ai1_through_ai5_and_replays_without_provider_call():
    provider = StaticImplementationProvider()
    runtime = ImplementationAgentRuntime(provider=provider, allowed_resources=(RESOURCE,))
    first = _run(runtime)
    second = _run(runtime)
    assert first.authority.allowed is True
    assert first.execution.status is ExecutionStatus.SUCCEEDED
    assert first.outcome.status is OutcomeStatus.SUCCEEDED
    assert first.proposal.unified_diff == VALID_DIFF
    assert first.proposal.request_fingerprint == first.request.request_fingerprint
    assert second.execution.status is ExecutionStatus.REPLAYED
    assert second.outcome.status is OutcomeStatus.REPLAYED
    assert second.proposal.proposal_id == first.proposal.proposal_id
    assert provider.calls == [first.request.request_fingerprint]
    assert len(runtime.authority_audit()) == 2
    assert len(runtime.execution_audit()) == 2


def test_command_identity_cannot_be_rebound_to_changed_instruction():
    provider = StaticImplementationProvider()
    runtime = ImplementationAgentRuntime(provider=provider, allowed_resources=(RESOURCE,))
    _run(runtime)
    with pytest.raises(ImplementationCommandConflictError):
        _run(runtime, instruction="Set VALUE to 3.")
    assert len(provider.calls) == 1


def test_unconfigured_repository_fails_closed_before_provider_execution():
    provider = StaticImplementationProvider()
    runtime = ImplementationAgentRuntime(provider=provider, allowed_resources=(RESOURCE,))
    with pytest.raises(ImplementationAgentAuthorityError) as exc:
        _run(runtime, resource="repository:other/project")
    assert exc.value.decision.allowed is False
    assert provider.calls == []


def test_context_is_not_silently_truncated_before_provider_execution():
    provider = StaticImplementationProvider()
    runtime = ImplementationAgentRuntime(provider=provider, allowed_resources=(RESOURCE,), max_context_bytes=1)
    with pytest.raises(ImplementationContextLimitError):
        _run(runtime)
    assert provider.calls == []


def test_sensitive_context_requires_an_explicit_operator_policy():
    provider = StaticImplementationProvider()
    runtime = ImplementationAgentRuntime(provider=provider, allowed_resources=(RESOURCE,))
    sensitive = (ContextItem(source="repository", key="src/app.py", value="VALUE = 1\n", sensitivity="sensitive"),)
    with pytest.raises(ValueError, match="sensitive context"):
        _run(runtime, context_items=sensitive)
    assert provider.calls == []


def test_invalid_provider_patch_is_a_failed_governed_execution():
    provider = StaticImplementationProvider("not a diff")
    runtime = ImplementationAgentRuntime(provider=provider, allowed_resources=(RESOURCE,))
    with pytest.raises(ImplementationAgentExecutionError) as exc:
        _run(runtime)
    assert exc.value.execution.status is ExecutionStatus.FAILED
    assert exc.value.outcome.status is OutcomeStatus.FAILED
    assert len(provider.calls) == 1


def test_openai_provider_uses_strict_output_without_leaking_key():
    captured: dict[str, object] = {}
    def transport(url, headers, body, timeout):
        captured.update(url=url, headers=dict(headers), body=body, timeout=timeout)
        return {"status": "completed", "output_text": json.dumps({"unified_diff": VALID_DIFF})}
    provider = OpenAIImplementationProvider(api_key="secret-test-key", model="implementation-model", transport=transport)
    candidate = provider.propose_patch(_request())
    assert candidate.unified_diff == VALID_DIFF
    assert captured["url"] == OPENAI_IMPLEMENTATION_RESPONSES_URL
    assert captured["headers"]["Authorization"] == "Bearer secret-test-key"
    assert b"secret-test-key" not in captured["body"]
    body = json.loads(captured["body"])
    assert body["store"] is False
    assert body["text"]["format"]["type"] == "json_schema"
    assert body["text"]["format"]["strict"] is True
    assert provider.provider_id == "openai.responses:implementation-model"


@pytest.mark.parametrize("url", ("http://api.openai.com/v1/responses", "https://attacker.example/v1/responses", "file:///tmp/responses.json"))
def test_openai_transport_rejects_non_allowlisted_endpoints(monkeypatch, url):
    called = False
    def urlopen(*_args, **_kwargs):
        nonlocal called
        called = True
        raise AssertionError("network transport must not be called")
    monkeypatch.setattr(urllib.request, "urlopen", urlopen)
    with pytest.raises(OpenAIImplementationProviderError, match="not allowed"):
        _http_transport(url, {}, b"{}", 1.0)
    assert called is False


def test_openai_provider_rejects_oversized_complete_context_without_transport():
    called = False
    def transport(*_args):
        nonlocal called
        called = True
        raise AssertionError("oversized input must not be sent")
    provider = OpenAIImplementationProvider(api_key="secret-test-key", model="implementation-model", max_input_bytes=1, transport=transport)
    with pytest.raises(OpenAIImplementationInputLimitError):
        provider.propose_patch(_request())
    assert called is False


def test_openai_provider_rejects_oversized_structured_output():
    provider = OpenAIImplementationProvider(api_key="secret-test-key", model="implementation-model", max_output_bytes=1, transport=lambda *_args: {"status": "completed", "output_text": json.dumps({"unified_diff": VALID_DIFF})})
    with pytest.raises(OpenAIImplementationResponseError, match="max_output_bytes"):
        provider.propose_patch(_request())


@pytest.mark.parametrize("response", ({"status": "incomplete"}, {"status": "completed", "output_text": "not-json"}, {"status": "completed", "output_text": json.dumps({"unified_diff": VALID_DIFF, "authority": "allow"})}))
def test_openai_provider_rejects_incomplete_or_malformed_output(response):
    provider = OpenAIImplementationProvider(api_key="secret-test-key", model="implementation-model", transport=lambda *_args: response)
    with pytest.raises(OpenAIImplementationResponseError):
        provider.propose_patch(_request())
