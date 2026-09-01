"""Control-plane swarm API tests (adapteret til main's SwarmTaskQueue-kontrakt)."""

import os
from datetime import datetime, timezone

os.environ.setdefault("DOR_JWT_SECRET_KEY", "test-secret-key-min-32-chars-long")
os.environ.setdefault("DOR_ENV", "test")
os.environ.setdefault("DOR_ADMIN_USERNAME", "admin")
os.environ.setdefault("DOR_ADMIN_PASSWORD", "admin")
os.environ.setdefault("DOR_ADMIN_ORGANIZATION_ID", "test-org")

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from api.auth import (
    bootstrap_configured_admin,
    create_access_token,
    fake_users_db,
    get_password_hash,
)
from api.dependencies import get_swarm_control_store
from api.endpoints import swarm as swarm_mod
from api.main import app
from infrastructure.persistence.models import Base, ProjectModel
from infrastructure.persistence.swarm_control_models import (
    SwarmDispatchControlModel,
    SwarmProjectDispatchModel,
)
from services.swarm_control_store import SwarmControlStore

client = TestClient(app)
_sessions = None


@pytest.fixture(autouse=True)
def _tenant_swarm_store(tmp_path, monkeypatch):
    global _sessions
    engine = create_engine(f"sqlite:///{tmp_path / 'swarm-api.db'}")
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


def _canonical_project(project_id: str, owner: str = "admin") -> None:
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
                created_by=owner,
                created_at=now,
                updated_at=now,
                revision=0,
            )
        )
        session.commit()


def _auth_token() -> str:
    username = os.environ.get("DOR_ADMIN_USERNAME", "admin")
    password = os.environ.get("DOR_ADMIN_PASSWORD", "admin")
    r = client.post("/auth/token", data={"username": username, "password": password})
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


def _auth_header() -> dict[str, str]:
    return {"Authorization": f"Bearer {_auth_token()}"}


def test_swarm_flow_requires_auth():
    r = client.post(
        "/api/v1/swarm/projects", json={"project_id": "p-auth", "requirements": {}}
    )
    assert r.status_code in (401, 403)


def test_full_swarm_flow():
    h = _auth_header()
    _canonical_project("p1")

    # 1. Start project with a task plan
    r = client.post(
        "/api/v1/swarm/projects",
        json={
            "project_id": "p1",
            "requirements": {"goal": "Build order API"},
            "tasks": [
                {
                    "id": "T1",
                    "name": "Build API",
                    "dependencies": [],
                    "capabilities": ["code"],
                    "priority": 1,
                },
                {
                    "id": "T2",
                    "name": "Test API",
                    "dependencies": ["T1"],
                    "capabilities": ["test"],
                    "priority": 2,
                },
            ],
        },
        headers=h,
    )
    assert r.status_code == 201, r.text
    assert r.json()["enqueued"] == 2

    # Status report
    r = client.get("/api/v1/swarm/projects/p1", headers=h)
    assert r.status_code == 200
    assert r.json()["total"] == 2

    # 2. Worker claims T1
    r = client.post(
        "/api/v1/swarm/workers/claim",
        json={"worker_id": "w1", "capabilities": ["code"]},
        headers=h,
    )
    assert r.status_code == 200
    body = r.json()
    assert body["claimed"] is True
    assert body["task"]["task_id"] == "T1"

    # 3. Heartbeat extends lease
    r = client.post(
        "/api/v1/swarm/workers/heartbeat",
        json={"worker_id": "w1", "task_id": "T1"},
        headers=h,
    )
    assert r.status_code == 200
    assert r.json()["ok"] is True

    # 4. Complete T1 → T2 becomes claimable
    r = client.post(
        "/api/v1/swarm/workers/complete",
        json={
            "worker_id": "w1",
            "task_id": "T1",
            "success": True,
            "patch_result": {"lines": 40},
        },
        headers=h,
    )
    assert r.status_code == 200
    assert r.json()["ok"] is True

    # 5. Claim T2 with test capability
    r = client.post(
        "/api/v1/swarm/workers/claim",
        json={"worker_id": "w2", "capabilities": ["test"]},
        headers=h,
    )
    assert r.status_code == 200
    assert r.json()["claimed"] is True
    assert r.json()["task"]["task_id"] == "T2"

    # 6. Fail T2 → task is retried (returned to PENDING with retry_count=1)
    r = client.post(
        "/api/v1/swarm/workers/complete",
        json={
            "worker_id": "w2",
            "task_id": "T2",
            "success": False,
            "error": "test failed",
        },
        headers=h,
    )
    assert r.status_code == 200
    assert r.json()["ok"] is True

    # Final status: 1 completed, T2 back to PENDING for retry
    r = client.get("/api/v1/swarm/projects/p1", headers=h)
    counts = r.json()["counts"]
    assert counts["COMPLETED"] == 1
    assert counts["PENDING"] == 1
    assert counts["FAILED"] == 0


def test_pause_blocks_claiming():
    h = _auth_header()
    _canonical_project("p2")

    r = client.post(
        "/api/v1/swarm/projects",
        json={"project_id": "p2", "tasks": [{"id": "A", "name": "A"}]},
        headers=h,
    )
    assert r.status_code == 201

    client.post("/api/v1/swarm/pause", headers=h)
    r = client.post(
        "/api/v1/swarm/workers/claim",
        json={"worker_id": "w3", "capabilities": []},
        headers=h,
    )
    assert r.json()["claimed"] is False
    assert r.json()["reason"] == "paused"

    client.post("/api/v1/swarm/resume", headers=h)
    r = client.post(
        "/api/v1/swarm/workers/claim",
        json={"worker_id": "w3", "capabilities": []},
        headers=h,
    )
    assert r.json()["claimed"] is True


def test_project_status_is_bound_to_authenticated_principal():
    h = _auth_header()
    _canonical_project("principal-owned")
    response = client.post(
        "/api/v1/swarm/projects",
        json={"project_id": "principal-owned"},
        headers=h,
    )
    assert response.status_code == 201

    fake_users_db["project-outsider"] = {
        "username": "project-outsider",
        "email": None,
        "full_name": "Project Outsider",
        "disabled": False,
        "organization_id": "test-org",
        "hashed_password": get_password_hash("unused"),
    }
    outsider_token = create_access_token({"sub": "project-outsider", "org": "test-org"})
    response = client.get(
        "/api/v1/swarm/projects/principal-owned",
        headers={"Authorization": f"Bearer {outsider_token}"},
    )
    assert response.status_code == 403
