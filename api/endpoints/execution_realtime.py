"""Browser-compatible realtime transport for execution workflows.

Native browser WebSocket and EventSource clients cannot attach arbitrary
Authorization headers. This module therefore adds a short-lived, scoped
HttpOnly stream-session cookie while retaining Bearer-header support for
non-browser clients.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, Response, WebSocket, WebSocketDisconnect
from fastapi.responses import StreamingResponse
from starlette.websockets import WebSocketState

from api.auth import User, authenticate_access_token, get_configured_user, get_current_active_user
from api.dependencies import get_dor
from api.endpoints.execution import _orchestrator, _workflow_project_id
from runtime.core import DORRuntime
from services.event_bus import default_event_bus, project_topic

router = APIRouter(prefix="/api/v1/execution", tags=["execution-realtime"])

STREAM_SESSION_COOKIE = "eiraos_execution_stream"
STREAM_SESSION_TTL_SECONDS = 300
_STREAM_SESSIONS: dict[str, dict[str, Any]] = {}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _session_digest(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _purge_expired_sessions() -> None:
    now = _now()
    expired = [key for key, value in _STREAM_SESSIONS.items() if value["expires_at"] <= now]
    for key in expired:
        _STREAM_SESSIONS.pop(key, None)


def _create_session(workflow_id: str, user: User) -> tuple[str, datetime]:
    _purge_expired_sessions()
    token = secrets.token_urlsafe(32)
    expires_at = _now() + timedelta(seconds=STREAM_SESSION_TTL_SECONDS)
    _STREAM_SESSIONS[_session_digest(token)] = {
        "username": user.username,
        "organization_id": user.organization_id,
        "workflow_id": workflow_id,
        "expires_at": expires_at,
    }
    return token, expires_at


def _resolve_session(token: str | None, workflow_id: str) -> User | None:
    if not token:
        return None
    _purge_expired_sessions()
    session = _STREAM_SESSIONS.get(_session_digest(token))
    if session is None or session["workflow_id"] != workflow_id:
        return None
    user = get_configured_user(session["username"])
    if user is None or user.disabled:
        return None
    if user.organization_id != session["organization_id"]:
        return None
    return User.model_validate(user)


def _header_token(headers: Any) -> str | None:
    authorization = headers.get("authorization", "")
    scheme, _, token = authorization.partition(" ")
    return token if scheme.lower() == "bearer" and token else None


def _authenticate_websocket(websocket: WebSocket, workflow_id: str) -> User | None:
    session_user = _resolve_session(websocket.cookies.get(STREAM_SESSION_COOKIE), workflow_id)
    if session_user is not None:
        return session_user
    token = _header_token(websocket.headers)
    if not token:
        return None
    try:
        return authenticate_access_token(token)
    except HTTPException:
        return None


def _authenticate_http_stream(request: Request, workflow_id: str) -> User:
    session_user = _resolve_session(request.cookies.get(STREAM_SESSION_COOKIE), workflow_id)
    if session_user is not None:
        return session_user
    token = _header_token(request.headers)
    if token:
        try:
            return authenticate_access_token(token)
        except HTTPException:
            pass
    raise HTTPException(status_code=401, detail="Could not validate credentials")


def _authorize_workflow(dor: DORRuntime, workflow_id: str, user: User) -> tuple[Any, str]:
    workflow = _orchestrator(dor)._get_workflow(workflow_id)
    if workflow is None:
        raise HTTPException(status_code=404, detail="execution_not_found")
    organization_id = getattr(workflow, "context", {}).get("organization_id") or getattr(
        workflow, "metadata", {}
    ).get("organization_id")
    if organization_id and organization_id != user.organization_id:
        raise HTTPException(status_code=403, detail="Execution access denied")
    project_id = _workflow_project_id(workflow)
    return workflow, project_id


@router.post("/stream-session/{workflow_id}")
def create_stream_session(
    workflow_id: str,
    response: Response,
    dor: DORRuntime = Depends(get_dor),
    current_user: User = Depends(get_current_active_user),
) -> dict[str, str]:
    """Create a short-lived HttpOnly cookie for native browser streams."""
    workflow, _ = _authorize_workflow(dor, workflow_id, current_user)
    token, expires_at = _create_session(workflow.id, current_user)
    response.set_cookie(
        STREAM_SESSION_COOKIE,
        token,
        max_age=STREAM_SESSION_TTL_SECONDS,
        expires=expires_at,
        httponly=True,
        secure=os.getenv("DOR_ENV", "development").lower() == "production",
        samesite="lax",
        path="/api/v1/execution",
    )
    return {"workflow_id": workflow.id, "expires_at": expires_at.isoformat()}


@router.delete("/stream-session/{workflow_id}", status_code=204)
def delete_stream_session(
    workflow_id: str,
    response: Response,
    current_user: User = Depends(get_current_active_user),
) -> None:
    del workflow_id, current_user
    response.delete_cookie(STREAM_SESSION_COOKIE, path="/api/v1/execution")


def _subscribe_stream(workflow: Any, queue: asyncio.Queue[dict[str, Any]]) -> tuple[str, str]:
    topic = project_topic(_workflow_project_id(workflow))

    def on_event(_event_type: str, envelope: dict[str, Any]) -> None:
        if envelope.get("payload", {}).get("workflow_id") != workflow.id:
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

    return topic, default_event_bus.subscribe(topic, on_event)


@router.websocket("/ws/{workflow_id}")
async def browser_execution_websocket(websocket: WebSocket, workflow_id: str) -> None:
    """WebSocket transport using an HttpOnly cookie or Bearer header."""
    user = _authenticate_websocket(websocket, workflow_id)
    if user is None:
        await websocket.close(code=1008, reason="authentication required")
        return
    try:
        dor = get_dor()
        workflow, project_id = _authorize_workflow(dor, workflow_id, user)
    except HTTPException:
        await websocket.close(code=1008, reason="execution access denied")
        return

    await websocket.accept()
    queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=256)
    topic, sub_id = _subscribe_stream(workflow, queue)
    stop = asyncio.Event()
    await websocket.send_json(
        {"event_type": "WS_CONNECTED", "workflow_id": workflow_id, "topic": topic, "project_id": project_id}
    )

    async def forward() -> None:
        while not stop.is_set():
            try:
                event = await asyncio.wait_for(queue.get(), timeout=1.0)
            except asyncio.TimeoutError:
                continue
            if websocket.client_state != WebSocketState.CONNECTED:
                return
            await websocket.send_json(event)

    forward_task = asyncio.create_task(forward())
    try:
        while True:
            message = await websocket.receive_json()
            if str(message.get("type", "")).lower() == "ping":
                await websocket.send_json({"event_type": "PONG", "workflow_id": workflow_id})
            else:
                await websocket.send_json({"event_type": "ERROR", "message": "unsupported_client_message"})
    except (WebSocketDisconnect, asyncio.CancelledError):
        pass
    finally:
        stop.set()
        forward_task.cancel()
        try:
            await forward_task
        except asyncio.CancelledError:
            pass
        default_event_bus.unsubscribe(topic, sub_id)
        if websocket.client_state == WebSocketState.CONNECTED:
            await websocket.close()


@router.get("/events/{workflow_id}")
async def browser_execution_sse(
    workflow_id: str,
    request: Request,
    dor: DORRuntime = Depends(get_dor),
) -> StreamingResponse:
    """SSE fallback; native EventSource authenticates with the stream cookie."""
    current_user = _authenticate_http_stream(request, workflow_id)
    workflow, _ = _authorize_workflow(dor, workflow_id, current_user)
    queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=256)
    topic, sub_id = _subscribe_stream(workflow, queue)

    async def generator() -> Any:
        try:
            yield ": connected\n\n"
            yield f"event: SSE_CONNECTED\ndata: {json.dumps({'workflow_id': workflow_id})}\n\n"
            while True:
                try:
                    envelope = await asyncio.wait_for(queue.get(), timeout=15.0)
                    yield f"event: {envelope.get('event_type', 'message')}\ndata: {json.dumps(envelope)}\n\n"
                except asyncio.TimeoutError:
                    yield f": heartbeat {_now().isoformat()}\n\n"
        finally:
            default_event_bus.unsubscribe(topic, sub_id)

    return StreamingResponse(
        generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive", "X-Accel-Buffering": "no"},
    )
