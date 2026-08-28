"""Black-box acceptance test through a real Uvicorn HTTP server."""

from __future__ import annotations

import os
import socket
import subprocess
import sys
import time
from pathlib import Path

import httpx
import pytest

REQUIREMENTS = """
project_name: Health API
project_description: HTTP acceptance service
version: 1.0.0
requirements:
  - id: REQ-001
    description: Health endpoint
    acceptance_criteria:
      - GET /health returns 200
"""


def _free_port() -> int:
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


def _start_server(repo: Path, env: dict[str, str], port: int) -> subprocess.Popen:
    process = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "api.main:app",
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
            "--log-level",
            "warning",
        ],
        cwd=repo,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    base_url = f"http://127.0.0.1:{port}"
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        if process.poll() is not None:
            output = process.stdout.read() if process.stdout else ""
            raise AssertionError(f"Uvicorn exited during startup:\n{output}")
        try:
            with httpx.Client(trust_env=False, timeout=0.5) as client:
                if client.get(f"{base_url}/health").status_code == 200:
                    return process
        except httpx.TransportError:
            time.sleep(0.1)
    process.terminate()
    raise AssertionError("Uvicorn did not become healthy")


def _stop_server(process: subprocess.Popen) -> None:
    process.terminate()
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)


def _token(client: httpx.Client) -> str:
    response = client.post(
        "/auth/token",
        data={"username": "acceptance-user", "password": "acceptance-password"},
    )
    assert response.status_code == 200, response.text
    return response.json()["access_token"]


@pytest.mark.acceptance
def test_pipeline_over_real_http_survives_server_restart(tmp_path: Path) -> None:
    repo = Path(__file__).resolve().parents[2]
    database = tmp_path / "acceptance.db"
    queue = tmp_path / "queue.db"
    port = _free_port()
    base_url = f"http://127.0.0.1:{port}"
    env = {
        **os.environ,
        "DATABASE_URL": f"sqlite:///{database}",
        "DOR_PIPELINE_DATABASE_URL": f"sqlite:///{database}",
        "DOR_PIPELINE_STATE_ORGANIZATION_ID": "acceptance-org",
        "DOR_PIPELINE_STATE_STORE_ID": "http-acceptance",
        "DOR_PIPELINE_QUEUE_PATH": str(queue),
        "DOR_ADMIN_USERNAME": "acceptance-user",
        "DOR_ADMIN_PASSWORD": "acceptance-password",
        "DOR_JWT_SECRET_KEY": "acceptance-only-jwt-secret-at-least-32-chars",
        "DOR_ENV": "test",
    }
    server = _start_server(repo, env, port)
    try:
        with httpx.Client(base_url=base_url, timeout=5, trust_env=False) as client:
            assert client.get("/health/ready").json() == {
                "status": "ready",
                "database": "ok",
            }
            token = _token(client)
            headers = {"Authorization": f"Bearer {token}"}
            start = client.post(
                "/pipeline/start",
                params={"organization_id": "acceptance-org"},
                headers=headers,
                json={"requirements_yaml": REQUIREMENTS},
            )
            assert start.status_code == 200, start.text
            workflow_id = start.json()["workflow_id"]

            terminal = {"released", "failed", "cancelled"}
            for _ in range(30):
                status_response = client.get(
                    f"/pipeline/{workflow_id}",
                    params={"organization_id": "acceptance-org"},
                    headers=headers,
                )
                assert status_response.status_code == 200, status_response.text
                pipeline = status_response.json()
                if pipeline["state_name"] in terminal:
                    break
                pending = [t for t in pipeline["tasks"] if t["status"] == "pending"]
                if pending:
                    claim = client.post(
                        "/pipeline/workers/claim",
                        headers=headers,
                        json={
                            "worker_id": "acceptance-worker",
                            "organization_id": "acceptance-org",
                            "capabilities": [],
                        },
                    )
                    assert claim.status_code == 200, claim.text
                    task = claim.json()["task"]
                    assert task["task_id"] == pending[0]["id"]
                    completed = client.post(
                        "/pipeline/workers/complete",
                        headers=headers,
                        json={
                            "worker_id": "acceptance-worker",
                            "organization_id": "acceptance-org",
                            "task_id": task["task_id"],
                            "result": {task["name"]: {"verified": True}},
                        },
                    )
                    assert completed.status_code == 200, completed.text
                    continue
                gates = client.get(
                    f"/api/v1/pipeline-gates/{workflow_id}",
                    params={"organization_id": "acceptance-org"},
                    headers=headers,
                )
                assert gates.status_code == 200, gates.text
                pending_gates = [gate for gate in gates.json() if gate["pending"]]
                assert len(pending_gates) == 1
                approved = client.post(
                    "/api/v1/pipeline-gates/approve",
                    params={"organization_id": "acceptance-org"},
                    headers=headers,
                    json={
                        "workflow_id": workflow_id,
                        "gate_id": pending_gates[0]["id"],
                        "decision": "approved",
                    },
                )
                assert approved.status_code == 200, approved.text
            else:
                raise AssertionError("pipeline did not reach a terminal state")
            assert pipeline["state_name"] == "released"
    finally:
        _stop_server(server)

    restarted = _start_server(repo, env, port)
    try:
        with httpx.Client(base_url=base_url, timeout=5, trust_env=False) as client:
            headers = {"Authorization": f"Bearer {_token(client)}"}
            restored = client.get(
                f"/pipeline/{workflow_id}",
                params={"organization_id": "acceptance-org"},
                headers=headers,
            )
            assert restored.status_code == 200, restored.text
            assert restored.json()["state_name"] == "released"
            denied = client.get(
                f"/pipeline/{workflow_id}",
                params={"organization_id": "another-org"},
                headers=headers,
            )
            assert denied.status_code == 404
    finally:
        _stop_server(restarted)
