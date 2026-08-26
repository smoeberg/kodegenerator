"""Synchronous and asynchronous Python client for the Kodegenerator API."""
from __future__ import annotations

import json
from collections.abc import AsyncIterator, Iterator, Mapping
from typing import Any

import httpx

from .models import ApprovalRequiredError, GateApproval, KodegenAPIError, ProjectStatus, QuotaExceededError, SwarmEvent, TaskResponse


class KodegeneratorClient:
    """Ergonomic API client supporting sync calls and async context management."""

    def __init__(self, base_url: str, api_key: str, *, timeout: float = 30.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.timeout = timeout
        self._client = httpx.Client(base_url=self.base_url, timeout=timeout, headers=self._headers())
        self._async_client = httpx.AsyncClient(base_url=self.base_url, timeout=timeout, headers=self._headers())

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.api_key}", "Accept": "application/json"}

    def _error(self, response: httpx.Response) -> KodegenAPIError:
        try: detail: Any = response.json()
        except ValueError: detail = response.text
        message = detail.get("detail", detail) if isinstance(detail, dict) else detail
        if response.status_code == 429: return QuotaExceededError(str(message), status_code=response.status_code, response=response)
        if response.status_code in (401, 403) and isinstance(detail, dict) and detail.get("approval_required"):
            return ApprovalRequiredError(str(message), status_code=response.status_code, response=response)
        return KodegenAPIError(str(message), status_code=response.status_code, response=response)

    def _request(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        response = self._client.request(method, path, **kwargs)
        if response.is_error: raise self._error(response)
        return response

    async def _arequest(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        response = await self._async_client.request(method, path, **kwargs)
        if response.is_error: raise self._error(response)
        return response

    def submit_task(self, task: Mapping[str, Any] | str, *, project_id: str | None = None) -> TaskResponse:
        """Submit a task and return its typed response."""
        payload = dict(task) if isinstance(task, Mapping) else {"task": task}
        if project_id is not None: payload["project_id"] = project_id
        return TaskResponse.model_validate(self._request("POST", "/tasks", json=payload).json())

    def get_project_status(self, project_id: str) -> ProjectStatus:
        """Fetch the current status of a project."""
        return ProjectStatus.model_validate(self._request("GET", f"/projects/{project_id}/status").json())

    def stream_events(self, project_id: str) -> Iterator[SwarmEvent]:
        """Stream newline-delimited JSON events synchronously."""
        with self._client.stream("GET", f"/projects/{project_id}/events") as response:
            if response.is_error: raise self._error(response)
            for line in response.iter_lines():
                if line: yield SwarmEvent.model_validate(json.loads(line.removeprefix("data: ")))

    def approve_gate(self, project_id: str, gate_id: str, *, approved: bool = True) -> GateApproval:
        """Approve or reject a project gate."""
        return GateApproval.model_validate(self._request("POST", f"/projects/{project_id}/gates/{gate_id}/approve", json={"approved": approved}).json())

    async def asubmit_task(self, task: Mapping[str, Any] | str, *, project_id: str | None = None) -> TaskResponse:
        """Asynchronously submit a task."""
        payload = dict(task) if isinstance(task, Mapping) else {"task": task}
        if project_id is not None: payload["project_id"] = project_id
        return TaskResponse.model_validate((await self._arequest("POST", "/tasks", json=payload)).json())

    async def aget_project_status(self, project_id: str) -> ProjectStatus:
        """Asynchronously fetch project status."""
        return ProjectStatus.model_validate((await self._arequest("GET", f"/projects/{project_id}/status")).json())

    async def astream_events(self, project_id: str) -> AsyncIterator[SwarmEvent]:
        """Asynchronously stream project events."""
        response = await self._async_client.stream("GET", f"/projects/{project_id}/events").__aenter__()
        try:
            if response.is_error: raise self._error(response)
            async for line in response.aiter_lines():
                if line: yield SwarmEvent.model_validate(json.loads(line.removeprefix("data: ")))
        finally: await response.aclose()

    async def aapprove_gate(self, project_id: str, gate_id: str, *, approved: bool = True) -> GateApproval:
        """Asynchronously approve or reject a project gate."""
        return GateApproval.model_validate((await self._arequest("POST", f"/projects/{project_id}/gates/{gate_id}/approve", json={"approved": approved})).json())

    def close(self) -> None:
        """Close synchronous and asynchronous transports when used outside async context."""
        self._client.close()

    async def __aenter__(self) -> "KodegeneratorClient":
        """Enter an asynchronous client context."""
        return self

    async def __aexit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        """Close the asynchronous transport."""
        await self._async_client.aclose()
        self._client.close()
