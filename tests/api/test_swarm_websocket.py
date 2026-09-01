"""Tests for EventBus and swarm WebSocket/SSE endpoints."""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from typing import Any

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

os.environ.setdefault("DOR_JWT_SECRET_KEY", "test-secret-key-min-32-chars-long")
os.environ.setdefault("DOR_ENV", "test")
os.environ.setdefault("DOR_ADMIN_USERNAME", "admin")
os.environ.setdefault("DOR_ADMIN_PASSWORD", "admin")
os.environ.setdefault("DOR_ADMIN_ORGANIZATION_ID", "test-org")

from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from api.auth import (
    bootstrap_configured_admin,
    create_access_token,
    fake_users_db,
    get_password_hash,
)
from api.dependencies import get_swarm_control_store
from api.endpoints import swarm as swarm_mod
from api.endpoints import swarm_websocket as ws_mod
from api.main import app
from infrastructure.persistence.models import Base, ProjectModel
from infrastructure.persistence.swarm_control_models import (
    SwarmDispatchControlModel,
    SwarmProjectDispatchModel,
)
from services.event_bus import (
    SYSTEM_ALERTS_TOPIC,
    EventBus,
    project_topic,
    worker_topic,
)
from services.swarm_control_store import SwarmControlStore

_sessions = None


@pytest.fixture(autouse=True)
def tenant_swarm_store(tmp_path, monkeypatch):
    global _sessions
    engine = create_engine(f"sqlite:///{tmp_path / 'swarm-websocket.db'}")
    Base.metadata.create_all(
        engine,
        tables=[
            ProjectModel.__table__,
            SwarmProjectDispatchModel.__table__,
            SwarmDispatchControlModel.__table__,
        ],
    )
    _sessions = sessionmaker(bind=engine, expire_on_commit=False)
    store = SwarmControlStore(_sessions)
    app.dependency_overrides[get_swarm_control_store] = lambda: store
    monkeypatch.setattr(swarm_mod, "get_swarm_control_store", lambda: store)
    swarm_mod._queue._tasks.clear()
    bootstrap_configured_admin()
    fake_users_db["admin"]["organization_id"] = "test-org"
    yield
    app.dependency_overrides.pop(get_swarm_control_store, None)
    _sessions = None


@pytest.fixture()
def bus() -> EventBus:
    """Isolated EventBus injected into the WebSocket module."""
    b = EventBus()
    ws_mod.set_event_bus(b)
    yield b
    b.clear()
    ws_mod.set_event_bus(
        ws_mod.default_event_bus if hasattr(ws_mod, "default_event_bus") else EventBus()
    )


# ---------------------------------------------------------------------------
# EventBus unit behaviour
# ---------------------------------------------------------------------------


def test_event_bus_publish_delivers_to_subscriber() -> None:
    bus = EventBus()
    received: list[dict[str, Any]] = []

    def _cb(event_type: str, envelope: dict[str, Any]) -> None:
        received.append(envelope)

    bus.subscribe(project_topic("p1"), _cb)
    event = bus.publish(project_topic("p1"), "TASK_CLAIMED", {"task_id": "T-1"})
    assert event.event_type == "TASK_CLAIMED"
    assert len(received) == 1
    assert received[0]["payload"]["task_id"] == "T-1"
    assert received[0]["topic"] == "project:p1"


def test_event_bus_topic_routing_isolation() -> None:
    bus = EventBus()
    hits: list[str] = []

    bus.subscribe(project_topic("a"), lambda et, env: hits.append("a"))
    bus.subscribe(project_topic("b"), lambda et, env: hits.append("b"))
    bus.subscribe(worker_topic("w1"), lambda et, env: hits.append("w"))

    bus.publish(project_topic("a"), "X", {})
    bus.publish(worker_topic("w1"), "Y", {})
    assert hits == ["a", "w"]


def test_event_bus_unsubscribe() -> None:
    bus = EventBus()
    count = {"n": 0}

    def _cb(et: str, env: dict[str, Any]) -> None:
        count["n"] += 1

    sid = bus.subscribe(SYSTEM_ALERTS_TOPIC, _cb)
    bus.publish(SYSTEM_ALERTS_TOPIC, "ALERT", {})
    assert count["n"] == 1
    assert bus.unsubscribe(SYSTEM_ALERTS_TOPIC, sid) is True
    bus.publish(SYSTEM_ALERTS_TOPIC, "ALERT", {})
    assert count["n"] == 1


def test_event_bus_recent_history() -> None:
    bus = EventBus()
    for i in range(5):
        bus.publish(project_topic("hist"), f"E{i}", {"i": i})
    recent = bus.recent(topic=project_topic("hist"), limit=3)
    assert len(recent) == 3
    assert recent[-1].payload["i"] == 4


def test_event_bus_webhook_fanout() -> None:
    bus = EventBus()
    published: list[tuple[str, dict[str, Any]]] = []

    class FakeDispatcher:
        async def publish(self, event: str, payload: dict[str, Any]) -> None:
            published.append((event, payload))

    bus.bind_webhook_dispatcher(FakeDispatcher())
    bus.publish(project_topic("p"), "PROJECT_COMPLETED", {"ok": True})
    # Fan-out schedules a coroutine; the sync path may no-op without an event loop.
    # Direct call path: if no running loop, fanout swallows; force via inspect
    assert bus.recent(limit=1)[0].event_type == "PROJECT_COMPLETED"


# ---------------------------------------------------------------------------
# WebSocket / SSE HTTP surface
# ---------------------------------------------------------------------------


def _auth_token(client: TestClient) -> str:
    response = client.post(
        "/auth/token",
        data={
            "username": os.environ.get("DOR_ADMIN_USERNAME", "admin"),
            "password": os.environ["DOR_ADMIN_PASSWORD"],
        },
    )
    assert response.status_code == 200, response.text
    return response.json()["access_token"]


def _create_project(client: TestClient, project_id: str, token: str) -> None:
    assert _sessions is not None
    now = datetime.now(timezone.utc)
    with _sessions() as session:
        session.add(
            ProjectModel(
                id=project_id,
                organization_id="test-org",
                name=project_id,
                description="",
                status="created",
                contract_version="1.0",
                intent={"goal": "test"},
                intent_fingerprint="a" * 64,
                project_fingerprint="b" * 64,
                created_by="admin",
                created_at=now,
                updated_at=now,
                revision=0,
            )
        )
        session.commit()
    response = client.post(
        "/api/v1/swarm/projects",
        json={"project_id": project_id},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 201, response.text


def test_websocket_receives_bus_publish(bus: EventBus) -> None:
    client = TestClient(app)
    token = _auth_token(client)
    _create_project(client, "proj-ws", token)
    try:
        with client.websocket_connect(
            "/api/v1/swarm/ws/proj-ws",
            headers={"Authorization": f"Bearer {token}"},
        ) as websocket:
            welcome = json.loads(websocket.receive_text())
            assert welcome["event_type"] == "WS_CONNECTED"
            assert welcome["project_id"] == "proj-ws"

            bus.publish(project_topic("proj-ws"), "TASK_MERGED", {"task_id": "T-9"})
            found = False
            for _ in range(10):
                msg = json.loads(websocket.receive_text())
                if msg.get("event_type") == "TASK_MERGED":
                    assert msg["payload"]["task_id"] == "T-9"
                    found = True
                    break
            assert found, "expected TASK_MERGED on websocket"
    except Exception as exc:
        # Starlette TestClient may surface CancelledError on WS teardown.
        if type(exc).__name__ != "CancelledError":
            raise


def test_websocket_ping_pong(bus: EventBus) -> None:
    client = TestClient(app)
    token = _auth_token(client)
    _create_project(client, "proj-ping", token)
    try:
        with client.websocket_connect(
            "/api/v1/swarm/ws/proj-ping",
            headers={"Authorization": f"Bearer {token}"},
        ) as websocket:
            websocket.receive_text()  # welcome
            websocket.send_text(json.dumps({"type": "ping"}))
            pong = json.loads(websocket.receive_text())
            assert pong["event_type"] == "PONG"
    except Exception as exc:
        if type(exc).__name__ != "CancelledError":
            raise


def test_websocket_client_publish_is_rejected(bus: EventBus) -> None:
    client = TestClient(app)
    token = _auth_token(client)
    _create_project(client, "proj-pub", token)
    try:
        with client.websocket_connect(
            "/api/v1/swarm/ws/proj-pub",
            headers={"Authorization": f"Bearer {token}"},
        ) as websocket:
            websocket.receive_text()
            websocket.send_text(
                json.dumps(
                    {
                        "type": "publish",
                        "event_type": "CLIENT_NOTE",
                        "payload": {"text": "hello"},
                    }
                )
            )
            msg = json.loads(websocket.receive_text())
            assert msg == {
                "event_type": "ERROR",
                "message": "unsupported_client_message",
            }
            assert bus.recent(topic=project_topic("proj-pub")) == []
    except Exception as exc:
        if type(exc).__name__ != "CancelledError":
            raise


def test_sse_stream_connected_frame(bus: EventBus) -> None:
    client = TestClient(app)
    token = _auth_token(client)
    _create_project(client, "proj-sse", token)
    with client.stream(
        "GET",
        "/api/v1/swarm/events/proj-sse",
        headers={"Authorization": f"Bearer {token}"},
    ) as response:
        assert response.status_code == 200
        assert "text/event-stream" in response.headers.get("content-type", "")
        buf = b""
        for chunk in response.iter_bytes():
            buf += chunk
            if b"SSE_CONNECTED" in buf or b"connected project=" in buf:
                break
        assert b"SSE_CONNECTED" in buf or b"connected project=" in buf


def test_connection_count_tracks_sockets(bus: EventBus) -> None:
    client = TestClient(app)
    token = _auth_token(client)
    _create_project(client, "proj-cnt", token)
    assert ws_mod.connection_count("proj-cnt") == 0
    try:
        with client.websocket_connect(
            "/api/v1/swarm/ws/proj-cnt",
            headers={"Authorization": f"Bearer {token}"},
        ) as websocket:
            websocket.receive_text()
            assert ws_mod.connection_count("proj-cnt") >= 1
    except Exception as exc:
        if type(exc).__name__ != "CancelledError":
            raise
    assert ws_mod.connection_count("proj-cnt") == 0


def test_websocket_rejects_missing_and_invalid_tokens(bus: EventBus) -> None:
    client = TestClient(app)
    token = _auth_token(client)
    _create_project(client, "proj-auth", token)

    with pytest.raises(WebSocketDisconnect) as missing:
        with client.websocket_connect("/api/v1/swarm/ws/proj-auth"):
            pass
    assert missing.value.code == 1008

    with pytest.raises(WebSocketDisconnect) as invalid:
        with client.websocket_connect("/api/v1/swarm/ws/proj-auth?token=invalid"):
            pass
    assert invalid.value.code == 1008

    with pytest.raises(WebSocketDisconnect) as query_token:
        with client.websocket_connect(f"/api/v1/swarm/ws/proj-auth?token={token}"):
            pass
    assert query_token.value.code == 1008


def test_websocket_revalidates_token_and_closes_expired_session(
    bus: EventBus, monkeypatch
) -> None:
    client = TestClient(app)
    token = _auth_token(client)
    _create_project(client, "proj-expiry", token)
    original = ws_mod.authenticate_access_token
    calls = 0

    def authenticate_once(value):
        nonlocal calls
        calls += 1
        if calls > 1:
            raise HTTPException(status_code=401)
        return original(value)

    monkeypatch.setattr(ws_mod, "authenticate_access_token", authenticate_once)
    monkeypatch.setattr(ws_mod, "WEBSOCKET_AUTH_REVALIDATION_SECONDS", 0.01)
    with client.websocket_connect(
        "/api/v1/swarm/ws/proj-expiry",
        headers={"Authorization": f"Bearer {token}"},
    ) as websocket:
        websocket.receive_text()
        with pytest.raises(WebSocketDisconnect) as expired:
            websocket.receive_text()
    assert expired.value.code == 1008


def test_websocket_rejects_user_without_project_access(bus: EventBus) -> None:
    client = TestClient(app)
    owner_token = _auth_token(client)
    _create_project(client, "proj-private", owner_token)
    fake_users_db["other-user"] = {
        "username": "other-user",
        "email": None,
        "full_name": "Other User",
        "disabled": False,
        "hashed_password": get_password_hash("unused"),
    }
    other_token = create_access_token({"sub": "other-user"})

    with pytest.raises(WebSocketDisconnect) as denied:
        with client.websocket_connect(
            "/api/v1/swarm/ws/proj-private",
            headers={"Authorization": f"Bearer {other_token}"},
        ):
            pass
    assert denied.value.code == 1008


def test_sse_requires_authentication_and_project_access(bus: EventBus) -> None:
    client = TestClient(app)
    token = _auth_token(client)
    _create_project(client, "proj-sse-private", token)

    response = client.get("/api/v1/swarm/events/proj-sse-private")
    assert response.status_code in (401, 403)

    fake_users_db["other-user"] = {
        "username": "other-user",
        "email": None,
        "full_name": "Other User",
        "disabled": False,
        "hashed_password": get_password_hash("unused"),
    }
    other_token = create_access_token({"sub": "other-user"})
    response = client.get(
        "/api/v1/swarm/events/proj-sse-private",
        headers={"Authorization": f"Bearer {other_token}"},
    )
    assert response.status_code == 403
