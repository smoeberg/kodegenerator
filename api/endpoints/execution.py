"""Development & Execution cockpit API.

This endpoint is a thin control-plane facade over the canonical pipeline
orchestrator. It deliberately does not introduce a second workflow engine.
Realtime notifications use the existing process-wide EventBus and therefore
share the repository's WebSocket/SSE transport conventions.
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field

from api.auth import User, authenticate_access_token, get_current_active_user
from api.dependencies import get_dor
from runtime.core import DORRuntime
from runtime.pipeline_orchestrator import PipelineOrchestrator
from runtime.pipeline_registry import get_pipeline_registry
from services.event_bus import default_event_bus, project_topic

router = APIRouter(prefix="/api/v1/execution", tags=["execution"])


class StartExecutionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    requirements_yaml: str = Field(min_length=1)
    organization_id: str = Field(min_length=1, max_length=256)


class AdvanceExecutionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str | None = Field(default=None, max_length=2000)


class GateDecisionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    gate_id: str = Field(min_length=1, max_length=256)
    decision: str = Field(default="approved", pattern="^(approved|rejected)$")


class ImplementationProposalRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=256)
    summary: str = Field(min_length=1, max_length=8000)
    files: list[dict[str, str]] = Field(default_factory=list)


_PROPOSALS: dict[str, list[dict[str, Any]]] = {}


def _orchestrator(dor: DORRuntime) -> PipelineOrchestrator:
    return get_pipeline_registry(dor).orchestrator


def _workflow_project_id(workflow: Any) -> str:
    context = dict(getattr(workflow, "context", {}) or {})
    metadata = dict(getattr(workflow, "metadata", {}) or {})
    return str(
        context.get("project_id")
        or metadata.get("project_id")
        or context.get("project_name")
        or getattr(workflow, "id", "unknown")
    )


def _emit(workflow: Any, event_type: str, payload: dict[str, Any] | None = None) -> None:
    project_id = _workflow_project_id(workflow)
    default_event_bus.publish(
        project_topic(project_id),
        event_type,
        {"workflow_id": workflow.id, **(payload or {})},
    )


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


@router.get("/{workflow_id}")
def get_execution(
    workflow_id: str,
    dor: DORRuntime = Depends(get_dor),
    _: User = Depends(get_current_active_user),
) -> dict[str, Any]:
    """Return the canonical workflow/pipeline snapshot used by the cockpit."""
    try:
        return _orchestrator(dor).get_pipeline_status(workflow_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail="execution_not_found") from exc


@router.post("/start")
def start_execution(
    request: StartExecutionRequest,
    dor: DORRuntime = Depends(get_dor),
    current_user: User = Depends(get_current_active_user),
) -> dict[str, Any]:
    """Start a governed software-factory execution and return its snapshot."""
    orch = _orchestrator(dor)
    try:
        workflow_id = orch.start_pipeline(
            requirements_yaml=request.requirements_yaml,
            organization_id=request.organization_id,
            created_by=current_user.username,
        )
        orch.advance_pipeline(workflow_id)
        workflow = orch._get_workflow(workflow_id)
        snapshot = orch.get_pipeline_status(workflow_id)
        if workflow is not None:
            _emit(workflow, "EXECUTION_STARTED", {"state": snapshot["current_state"]})
        return snapshot
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/{workflow_id}/advance")
def advance_execution(
    workflow_id: str,
    request: AdvanceExecutionRequest | None = None,
    dor: DORRuntime = Depends(get_dor),
    _: User = Depends(get_current_active_user),
) -> dict[str, Any]:
    """Advance the canonical pipeline; gates remain fail-closed."""
    orch = _orchestrator(dor)
    try:
        orch.advance_pipeline(workflow_id)
        workflow = orch._get_workflow(workflow_id)
        if workflow is None:
            raise ValueError("execution not found")
        _emit(
            workflow,
            "EXECUTION_ADVANCED",
            {"state": workflow.current_state.value, "reason": getattr(request, "reason", None)},
        )
        return orch.get_pipeline_status(workflow_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get("/{workflow_id}/gates")
def list_execution_gates(
    workflow_id: str,
    dor: DORRuntime = Depends(get_dor),
    _: User = Depends(get_current_active_user),
) -> list[dict[str, Any]]:
    orch = _orchestrator(dor)
    workflow = orch._get_workflow(workflow_id)
    if workflow is None:
        raise HTTPException(status_code=404, detail="execution_not_found")
    return [
        {
            "id": gate.id,
            "name": gate.name,
            "description": gate.description,
            "resolved": gate.decision_id is not None,
        }
        for gate in workflow.gates
    ]


@router.post("/{workflow_id}/gates/decide")
def decide_execution_gate(
    workflow_id: str,
    request: GateDecisionRequest,
    dor: DORRuntime = Depends(get_dor),
    current_user: User = Depends(get_current_active_user),
) -> dict[str, Any]:
    orch = _orchestrator(dor)
    try:
        approved = orch.approve_gate(
            workflow_id,
            request.gate_id,
            approver=current_user.username,
            decision=request.decision,
        )
        workflow = orch._get_workflow(workflow_id)
        if workflow is not None:
            _emit(
                workflow,
                "GATE_DECISION",
                {
                    "gate_id": request.gate_id,
                    "decision": request.decision,
                    "approved": approved,
                    "actor": current_user.username,
                },
            )
        return {
            "workflow_id": workflow_id,
            "gate_id": request.gate_id,
            "approved": approved,
            "status": workflow.current_state.value if workflow else None,
        }
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get("/{workflow_id}/proposals")
def list_implementation_proposals(
    workflow_id: str,
    _: User = Depends(get_current_active_user),
) -> list[dict[str, Any]]:
    return list(_PROPOSALS.get(workflow_id, []))


@router.post("/{workflow_id}/proposals", status_code=201)
def create_implementation_proposal(
    workflow_id: str,
    request: ImplementationProposalRequest,
    dor: DORRuntime = Depends(get_dor),
    current_user: User = Depends(get_current_active_user),
) -> dict[str, Any]:
    orch = _orchestrator(dor)
    workflow = orch._get_workflow(workflow_id)
    if workflow is None:
        raise HTTPException(status_code=404, detail="execution_not_found")
    proposal = {
        "id": f"proposal-{workflow_id[:8]}-{len(_PROPOSALS.get(workflow_id, [])) + 1}",
        "workflow_id": workflow_id,
        "title": request.title,
        "summary": request.summary,
        "files": [dict(item) for item in request.files],
        "status": "proposed",
        "created_by": current_user.username,
        "created_at": _utc_now(),
    }
    _PROPOSALS.setdefault(workflow_id, []).append(proposal)
    _emit(workflow, "IMPLEMENTATION_PROPOSAL_CREATED", {"proposal_id": proposal["id"]})
    return proposal


@router.websocket("/ws/{workflow_id}")
async def execution_websocket(websocket: WebSocket, workflow_id: str) -> None:
    """WebSocket-first execution stream; client may only send ping frames."""
    token = websocket.headers.get("authorization", "").partition(" ")[2]
    try:
        authenticate_access_token(token)
    except HTTPException:
        await websocket.close(code=1008, reason="authentication required")
        return

    orch = None
    try:
        await websocket.accept()
        topic = project_topic(workflow_id)
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=256)

        def on_event(_event_type: str, envelope: dict[str, Any]) -> None:
            if envelope.get("payload", {}).get("workflow_id") != workflow_id:
                return
            try:
                queue.put_nowait(dict(envelope))
            except asyncio.QueueFull:
                try:
                    queue.get_nowait()
                except asyncio.QueueEmpty:
                    pass
                try:
                    queue.put_nowait(dict(envelope))
                except asyncio.QueueFull:
                    pass

        sub_id = default_event_bus.subscribe(topic, on_event)
        await websocket.send_json({"event_type": "WS_CONNECTED", "workflow_id": workflow_id})

        async def forward() -> None:
            while True:
                event = await queue.get()
                await websocket.send_json(event)

        forward_task = asyncio.create_task(forward())
        try:
            while True:
                message = await websocket.receive_json()
                if str(message.get("type", "")).lower() == "ping":
                    await websocket.send_json({"event_type": "PONG", "timestamp": _utc_now()})
                else:
                    await websocket.send_json({"event_type": "ERROR", "message": "unsupported_client_message"})
        except WebSocketDisconnect:
            pass
        finally:
            forward_task.cancel()
            try:
                await forward_task
            except asyncio.CancelledError:
                pass
            default_event_bus.unsubscribe(topic, sub_id)
    except Exception:
        if websocket.client_state.value == 1:
            await websocket.close(code=1011, reason="realtime failure")


@router.get("/events/{workflow_id}")
async def execution_sse(
    workflow_id: str,
    _: User = Depends(get_current_active_user),
) -> StreamingResponse:
    """SSE fallback for clients that cannot establish a WebSocket."""
    topic = project_topic(workflow_id)
    queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=256)

    def on_event(_event_type: str, envelope: dict[str, Any]) -> None:
        if envelope.get("payload", {}).get("workflow_id") != workflow_id:
            return
        try:
            queue.put_nowait(dict(envelope))
        except asyncio.QueueFull:
            try:
                queue.get_nowait()
            except asyncio.QueueEmpty:
                pass

    sub_id = default_event_bus.subscribe(topic, on_event)

    async def generator() -> Any:
        try:
            yield ": connected\n\n"
            yield f"event: SSE_CONNECTED\ndata: {json.dumps({'workflow_id': workflow_id})}\n\n"
            while True:
                try:
                    envelope = await asyncio.wait_for(queue.get(), timeout=15)
                    yield f"event: {envelope.get('event_type', 'message')}\ndata: {json.dumps(envelope)}\n\n"
                except asyncio.TimeoutError:
                    yield f": heartbeat {_utc_now()}\n\n"
        finally:
            default_event_bus.unsubscribe(topic, sub_id)

    return StreamingResponse(
        generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive", "X-Accel-Buffering": "no"},
    )
