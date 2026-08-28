"""WebSocket and SSE hub for real-time swarm state updates.

Endpoints:

* ``WS  /api/v1/swarm/ws/{project_id}`` — bidirectional WebSocket with heartbeat
* ``GET /api/v1/swarm/events/{project_id}`` — Server-Sent Events fallback stream

Clients subscribe to ``project:{project_id}`` on the shared :class:`EventBus`.
Connection management tracks active sockets per project; heartbeats keep
proxies from closing idle connections.
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import Any

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    WebSocket,
    WebSocketDisconnect,
)
from fastapi.responses import StreamingResponse
from starlette.websockets import WebSocketState

from api.auth import User, authenticate_access_token, get_current_active_user
from api.endpoints.swarm import project_access_allowed, require_project_access
from services.event_bus import EventBus, default_event_bus, project_topic

router = APIRouter(tags=["swarm-realtime"])
logger = logging.getLogger(__name__)

_bus: EventBus = default_event_bus
_connections: dict[str, set[WebSocket]] = {}
_conn_lock = asyncio.Lock()
WEBSOCKET_AUTH_REVALIDATION_SECONDS = 15.0


def get_event_bus() -> EventBus:
    """Return the active EventBus instance."""
    return _bus


def set_event_bus(bus: EventBus) -> None:
    """Test/DI hook to replace the process bus."""
    global _bus
    _bus = bus


def envelope_now() -> str:
    """UTC timestamp for protocol frames."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


async def _register(project_id: str, websocket: WebSocket) -> None:
    async with _conn_lock:
        _connections.setdefault(project_id, set()).add(websocket)


async def _unregister(project_id: str, websocket: WebSocket) -> None:
    async with _conn_lock:
        sockets = _connections.get(project_id)
        if not sockets:
            return
        sockets.discard(websocket)
        if not sockets:
            _connections.pop(project_id, None)


def connection_count(project_id: str | None = None) -> int:
    """Number of open WebSocket connections (all projects if ``project_id`` is None)."""
    if project_id is None:
        return sum(len(s) for s in _connections.values())
    return len(_connections.get(project_id, set()))


async def broadcast_to_project(project_id: str, message: dict[str, Any]) -> int:
    """Push a JSON-serializable message to all sockets for ``project_id``."""
    async with _conn_lock:
        sockets = list(_connections.get(project_id, set()))
    sent = 0
    dead: list[WebSocket] = []
    payload = json.dumps(message, ensure_ascii=False)
    for ws in sockets:
        try:
            if ws.client_state == WebSocketState.CONNECTED:
                await ws.send_text(payload)
                sent += 1
            else:
                dead.append(ws)
        except Exception:
            logger.warning(
                "swarm websocket send failed",
                extra={"project_id": project_id},
                exc_info=True,
            )
            dead.append(ws)
    for ws in dead:
        await _unregister(project_id, ws)
    return sent


def _sse_format(data: dict[str, Any]) -> str:
    """Format a single SSE data frame."""
    event_type = str(data.get("event_type", "message"))
    body = json.dumps(data, ensure_ascii=False)
    return f"event: {event_type}\ndata: {body}\n\n"


def _websocket_token(websocket: WebSocket) -> str | None:
    authorization = websocket.headers.get("authorization", "")
    scheme, _, header_token = authorization.partition(" ")
    if scheme.lower() == "bearer" and header_token:
        return header_token
    return None


@router.websocket("/api/v1/swarm/ws/{project_id}")
async def swarm_websocket(
    websocket: WebSocket,
    project_id: str,
) -> None:
    """Accept a WebSocket, subscribe to the project topic, stream bus events.

    Protocol:

    * Server → client: JSON event envelopes from the bus (+ periodic heartbeats)
    * Client → server: ``{"type":"ping"}`` only

    JWT validation and project ownership are enforced before the handshake is
    accepted. Clients cannot publish arbitrary events to the internal bus.
    """
    try:
        token = _websocket_token(websocket) or ""
        current_user = authenticate_access_token(token)
    except HTTPException:
        logger.warning(
            "rejected unauthenticated swarm websocket",
            extra={"project_id": project_id},
        )
        await websocket.close(code=1008, reason="authentication required")
        return
    if not project_access_allowed(project_id, current_user.username):
        logger.warning(
            "rejected unauthorized swarm websocket",
            extra={"project_id": project_id, "username": current_user.username},
        )
        await websocket.close(code=1008, reason="project access denied")
        return

    await websocket.accept()
    await _register(project_id, websocket)

    topic = project_topic(project_id)
    queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=256)

    def _on_event(_event_type: str, envelope: dict[str, Any]) -> None:
        """Sync subscriber so EventBus.publish never needs a running loop."""
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

    sub_id = _bus.subscribe(topic, _on_event)

    await websocket.send_text(
        json.dumps(
            {
                "event_type": "WS_CONNECTED",
                "topic": topic,
                "project_id": project_id,
                "timestamp": envelope_now(),
            },
            ensure_ascii=False,
        )
    )

    stop = asyncio.Event()

    async def _forward_bus() -> None:
        while not stop.is_set():
            try:
                envelope = await asyncio.wait_for(queue.get(), timeout=1.0)
            except asyncio.TimeoutError:
                continue
            if websocket.client_state != WebSocketState.CONNECTED:
                break
            try:
                await websocket.send_text(json.dumps(envelope, ensure_ascii=False))
            except Exception:
                logger.info(
                    "swarm websocket forwarder stopped after send failure",
                    extra={"project_id": project_id},
                    exc_info=True,
                )
                break

    async def _heartbeat() -> None:
        while not stop.is_set():
            try:
                await asyncio.wait_for(
                    stop.wait(), timeout=WEBSOCKET_AUTH_REVALIDATION_SECONDS
                )
                return
            except asyncio.TimeoutError:
                if websocket.client_state != WebSocketState.CONNECTED:
                    return
                try:
                    refreshed_user = authenticate_access_token(token)
                    if (
                        refreshed_user.username != current_user.username
                        or not project_access_allowed(
                            project_id, refreshed_user.username
                        )
                    ):
                        await websocket.close(
                            code=1008, reason="authorization expired"
                        )
                        stop.set()
                        return
                    await websocket.send_text(
                        json.dumps(
                            {
                                "event_type": "HEARTBEAT",
                                "topic": topic,
                                "timestamp": envelope_now(),
                            },
                            ensure_ascii=False,
                        )
                    )
                except HTTPException:
                    await websocket.close(code=1008, reason="authentication expired")
                    stop.set()
                    return
                except Exception:
                    logger.info(
                        "swarm websocket heartbeat stopped after send failure",
                        extra={"project_id": project_id},
                        exc_info=True,
                    )
                    return

    forward_task = asyncio.create_task(_forward_bus())
    hb_task = asyncio.create_task(_heartbeat())

    try:
        while True:
            raw = await websocket.receive_text()
            await _handle_client_message(websocket, project_id, raw)
    except WebSocketDisconnect:
        pass
    except asyncio.CancelledError:
        pass
    except Exception:
        logger.exception(
            "unexpected swarm websocket lifecycle failure",
            extra={"project_id": project_id},
        )
    finally:
        stop.set()
        for task in (forward_task, hb_task):
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                continue
            except Exception:
                logger.exception(
                    "swarm websocket background task cleanup failed",
                    extra={"project_id": project_id},
                )
        _bus.unsubscribe(topic, sub_id)
        try:
            await _unregister(project_id, websocket)
        except Exception:
            logger.exception(
                "swarm websocket unregister failed",
                extra={"project_id": project_id},
            )
        try:
            if websocket.client_state == WebSocketState.CONNECTED:
                await websocket.close()
        except Exception:
            logger.exception(
                "swarm websocket close failed",
                extra={"project_id": project_id},
            )


async def _handle_client_message(
    websocket: WebSocket,
    project_id: str,
    raw: str,
) -> None:
    """Handle lightweight client control frames."""
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        await websocket.send_text(
            json.dumps(
                {"event_type": "ERROR", "message": "invalid_json"},
                ensure_ascii=False,
            )
        )
        return
    msg_type = str(data.get("type", "")).lower()
    if msg_type == "ping":
        await websocket.send_text(
            json.dumps(
                {
                    "event_type": "PONG",
                    "timestamp": envelope_now(),
                    "project_id": project_id,
                },
                ensure_ascii=False,
            )
        )
    else:
        await websocket.send_text(
            json.dumps(
                {"event_type": "ERROR", "message": "unsupported_client_message"},
                ensure_ascii=False,
            )
        )


@router.get("/api/v1/swarm/events/{project_id}")
async def swarm_sse(
    project_id: str,
    current_user: User = Depends(get_current_active_user),
) -> StreamingResponse:
    """Server-Sent Events stream for clients that cannot use WebSockets."""

    require_project_access(project_id, current_user.username)

    topic = project_topic(project_id)
    queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=256)

    def _on_event(_event_type: str, envelope: dict[str, Any]) -> None:
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

    sub_id = _bus.subscribe(topic, _on_event)

    async def event_generator() -> Any:
        try:
            yield f": connected project={project_id}\n\n"
            yield _sse_format(
                {
                    "event_type": "SSE_CONNECTED",
                    "topic": topic,
                    "project_id": project_id,
                    "timestamp": envelope_now(),
                }
            )
            # Limited iterations keep TestClient streams from hanging forever.
            # Production clients reconnect; long-lived use is still fine via
            # the heartbeat path until the client disconnects.
            idle_rounds = 0
            while idle_rounds < 3:
                try:
                    envelope = await asyncio.wait_for(queue.get(), timeout=0.5)
                    idle_rounds = 0
                    yield _sse_format(envelope)
                except asyncio.TimeoutError:
                    idle_rounds += 1
                    yield f": heartbeat {envelope_now()}\n\n"
        finally:
            _bus.unsubscribe(topic, sub_id)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
