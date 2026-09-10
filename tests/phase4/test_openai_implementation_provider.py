"""Contracts for the bounded OpenAI-compatible implementation provider."""
from __future__ import annotations

import json

import pytest

from phase4.context_packet.models import ContextPacket
from phase4.implementation_agent.models import (
    IMPLEMENTATION_ACTION,
    ChangeBudget,
    ImplementationRequest,
)
from phase4.implementation_agent.openai_provider import (
    OPENAI_IMPLEMENTATION_RESPONSES_URL,
    OpenAIImplementationProvider,
)


_PATCH = """diff --git a/app.py b/app.py
--- a/app.py
+++ b/app.py
@@ -1 +1 @@
-old
+new
"""


def _request() -> ImplementationRequest:
    packet = ContextPacket(
        packet_id="packet-1",
        agent_identity="implementation-agent",
        purpose=IMPLEMENTATION_ACTION,
        items=(),
        created_at="2026-09-09T00:00:00+00:00",
    )
    return ImplementationRequest(
        organization_id="org-a",
        agent_identity="implementation-agent",
        agent_role="implementation",
        resource="repository:org/repo",
        context_packet=packet,
        instruction="Make the approved change",
        allowed_paths=("app.py",),
        budget=ChangeBudget(max_files=1, max_changed_lines=2),
    )


def _capture_transport(captured: dict[str, object]):
    def transport(url, headers, body, timeout):
        captured["url"] = url
        captured["headers"] = dict(headers)
        captured["body"] = json.loads(body.decode("utf-8"))
        captured["timeout"] = timeout
        return {
            "status": "completed",
            "output_text": json.dumps({"unified_diff": _PATCH}),
        }

    return transport


def test_default_provider_keeps_canonical_openai_responses_endpoint() -> None:
    captured: dict[str, object] = {}
    provider = OpenAIImplementationProvider(
        api_key="secret-key",
        model="gpt-test",
        transport=_capture_transport(captured),
    )

    candidate = provider.propose_patch(_request())

    assert captured["url"] == OPENAI_IMPLEMENTATION_RESPONSES_URL
    assert captured["body"]["model"] == "gpt-test"
    assert candidate.unified_diff == _PATCH


def test_custom_base_url_is_pinned_to_its_responses_endpoint() -> None:
    captured: dict[str, object] = {}
    provider = OpenAIImplementationProvider(
        api_key="secret-key",
        model="gpt-test",
        base_url="https://ai.example.test/v1/",
        transport=_capture_transport(captured),
    )

    provider.propose_patch(_request())

    assert captured["url"] == "https://ai.example.test/v1/responses"


def test_base_url_with_embedded_credentials_is_rejected() -> None:
    with pytest.raises(ValueError, match="without credentials"):
        OpenAIImplementationProvider(
            api_key="secret-key",
            model="gpt-test",
            base_url="https://user:pass@ai.example.test/v1",
        )
