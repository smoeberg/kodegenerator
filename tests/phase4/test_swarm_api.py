"""Control-plane swarm API tests (adapteret til main's SwarmTaskQueue-kontrakt)."""
import os

os.environ.setdefault("DOR_JWT_SECRET_KEY", "test-secret-key-min-32-chars-long")
os.environ.setdefault("DOR_ENV", "test")
os.environ.setdefault("DOR_ADMIN_USERNAME", "admin")
os.environ.setdefault("DOR_ADMIN_PASSWORD", "admin")

from fastapi.testclient import TestClient

from api.main import app

client = TestClient(app)


def _auth_token() -> str:
    r = client.post("/auth/token", data={"username": "admin", "password": "admin"})
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


def _auth_header() -> dict[str, str]:
    return {"Authorization": f"Bearer {_auth_token()}"}


def test_swarm_flow_requires_auth():
    r = client.post("/api/v1/swarm/projects", json={"project_id": "p-auth", "requirements": {}})
    assert r.status_code in (401, 403)


def test_full_swarm_flow():
    h = _auth_header()

    # 1. Start project with a task plan
    r = client.post(
        "/api/v1/swarm/projects",
        json={
            "project_id": "p1",
            "requirements": {"goal": "Build order API"},
            "tasks": [
                {"id": "T1", "name": "Build API", "dependencies": [], "capabilities": ["code"], "priority": 1},
                {"id": "T2", "name": "Test API", "dependencies": ["T1"], "capabilities": ["test"], "priority": 2},
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
        json={"worker_id": "w1", "task_id": "T1", "success": True, "patch_result": {"lines": 40}},
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
        json={"worker_id": "w2", "task_id": "T2", "success": False, "error": "test failed"},
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

    r = client.post("/api/v1/swarm/projects", json={"project_id": "p2", "tasks": [{"id": "A", "name": "A"}]}, headers=h)
    assert r.status_code == 201

    client.post("/api/v1/swarm/pause", headers=h)
    r = client.post("/api/v1/swarm/workers/claim", json={"worker_id": "w3", "capabilities": []}, headers=h)
    assert r.json()["claimed"] is False
    assert r.json()["reason"] == "paused"

    client.post("/api/v1/swarm/resume", headers=h)
    r = client.post("/api/v1/swarm/workers/claim", json={"worker_id": "w3", "capabilities": []}, headers=h)
    assert r.json()["claimed"] is True
