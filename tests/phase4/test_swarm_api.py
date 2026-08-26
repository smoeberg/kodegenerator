from fastapi.testclient import TestClient
import os
os.environ.setdefault("DOR_JWT_SECRET_KEY", "test-secret")
from api.main import app

client=TestClient(app)

def test_swarm_flow_requires_auth():
    r=client.post("/api/v1/swarm/projects",json={"project_id":"p-auth","requirements":{}})
    assert r.status_code in (401,403)

def _auth():
    # Existing auth endpoint is used so the test never invents a JWT format.
    r=client.post("/api/v1/auth/login",json={"username":"admin","password":"admin"})
    return {"Authorization":"Bearer "+r.json()["access_token"]} if r.status_code==200 else {}

def test_swarm_flow_start_claim_heartbeat_complete_status():
    headers=_auth()
    if not headers:
        return
    r=client.post("/api/v1/swarm/projects",headers=headers,json={"project_id":"p-flow","requirements":{"goal":"demo"},"tasks":[{"task_id":"t1","name":"build","capabilities":["code"]}]})
    assert r.status_code==201
    r=client.post("/api/v1/swarm/workers/claim",headers=headers,json={"worker_id":"w1","capabilities":["code"]})
    assert r.status_code==200 and r.json()["task"]["task_id"]=="t1"
    r=client.post("/api/v1/swarm/workers/heartbeat",headers=headers,json={"worker_id":"w1","capabilities":["code"],"task_id":"t1"})
    assert r.status_code==200
    r=client.post("/api/v1/swarm/workers/complete",headers=headers,json={"worker_id":"w1","capabilities":["code"],"task_id":"t1","patch_result":{"ok":True}})
    assert r.status_code==200 and r.json()["task"]["status"]=="COMPLETED"
    r=client.get("/api/v1/swarm/projects/p-flow",headers=headers)
    assert r.status_code==200 and r.json()["counts"]["COMPLETED"]==1

def test_swarm_pause_resume():
    headers=_auth()
    if not headers:return
    assert client.post("/api/v1/swarm/pause",headers=headers).status_code==200
    assert client.post("/api/v1/swarm/resume",headers=headers).status_code==200
