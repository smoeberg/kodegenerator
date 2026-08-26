"""Tests for the public Kodegenerator Python SDK."""
from __future__ import annotations

import pytest
import respx
from httpx import Response

from sdk import ApprovalRequiredError, KodegenAPIError, KodegeneratorClient, QuotaExceededError


@respx.mock
def test_submit_task_uses_auth_and_typed_response() -> None:
    """Task submission sends the bearer token and parses a typed response."""
    route = respx.post("https://api.example.test/tasks").mock(return_value=Response(200, json={"task_id": "t1", "project_id": "p1", "status": "queued"}))
    client = KodegeneratorClient("https://api.example.test", "secret")
    result = client.submit_task({"prompt": "hello"})
    assert result.task_id == "t1" and route.calls[0].request.headers["Authorization"] == "Bearer secret"
    client.close()


@respx.mock
def test_project_status_and_gate_are_typed() -> None:
    """Status and gate endpoints return the expected Pydantic models."""
    respx.get("https://api.example.test/projects/p1/status").mock(return_value=Response(200, json={"project_id": "p1", "status": "running"}))
    respx.post("https://api.example.test/projects/p1/gates/g1/approve").mock(return_value=Response(200, json={"approved": True, "gate_id": "g1"}))
    client = KodegeneratorClient("https://api.example.test", "k")
    assert client.get_project_status("p1").status == "running"
    assert client.approve_gate("p1", "g1").approved is True
    client.close()


@pytest.mark.asyncio
@respx.mock
async def test_async_context_and_submit() -> None:
    """Async context management closes the transport and supports submission."""
    respx.post("https://api.example.test/tasks").mock(return_value=Response(200, json={"task_id": "t2", "status": "queued"}))
    async with KodegeneratorClient("https://api.example.test", "k") as client:
        result = await client.asubmit_task("build")
    assert result.task_id == "t2"


@pytest.mark.asyncio
@respx.mock
async def test_async_event_stream_parses_sse_lines() -> None:
    """SSE-style data lines are exposed as typed event models."""
    respx.get("https://api.example.test/projects/p/events").mock(return_value=Response(200, text='data: {"event":"TASK_DONE","data":{"id":"t"}}\n\ndata: {"event":"PROJECT_DONE","data":{}}\n'))
    async with KodegeneratorClient("https://api.example.test", "k") as client:
        events = [event async for event in client.astream_events("p")]
    assert [event.event for event in events] == ["TASK_DONE", "PROJECT_DONE"]


@pytest.mark.parametrize(("status", "detail", "expected"), [(429, "quota", QuotaExceededError), (403, {"approval_required": True, "detail": "gate"}, ApprovalRequiredError), (500, "boom", KodegenAPIError)])
@respx.mock
def test_errors_are_mapped_to_custom_exceptions(status: int, detail: object, expected: type[Exception]) -> None:
    """HTTP failures map to the documented SDK exception hierarchy."""
    respx.get("https://api.example.test/projects/p/status").mock(return_value=Response(status, json=detail if isinstance(detail, dict) else {"detail": detail}))
    client = KodegeneratorClient("https://api.example.test", "k")
    with pytest.raises(expected): client.get_project_status("p")
    client.close()
