"""Versioned Swarm Control-Plane REST API.

Exposes the swarm factory as an authenticated HTTP surface:

* POST /api/v1/swarm/projects            — start a new swarm project
* POST /api/v1/swarm/workers/claim       — worker claims the next eligible task
* POST /api/v1/swarm/workers/heartbeat   — worker extends its lease
* POST /api/v1/swarm/workers/complete    — worker reports success or failure
* GET  /api/v1/swarm/projects/{id}       — project status / counts
* POST /api/v1/swarm/pause | resume      — global dispatch control

The module talks ONLY to the public SwarmTaskQueue contract on ``main`` and
never rewrites or bypasses queue internals.
"""
from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from api.auth import User, get_current_active_user
from services.swarm_task_queue import SwarmTaskQueue, QueuedTaskStatus

router = APIRouter(prefix="/api/v1/swarm", tags=["swarm"])

# Single in-process swarm queue behind the control plane (main contract).
_queue: SwarmTaskQueue = SwarmTaskQueue()
_projects: dict[str, dict[str, Any]] = {}
_paused: bool = False


# --------------------------------------------------------------------------
# Schemas
# --------------------------------------------------------------------------
class StartProjectRequest(BaseModel):
    project_id: Optional[str] = None
    requirements: dict[str, Any] = Field(default_factory=dict)
    tasks: list[dict[str, Any]] = Field(default_factory=list)


class ClaimRequest(BaseModel):
    worker_id: str
    capabilities: list[str] = Field(default_factory=list)


class HeartbeatRequest(BaseModel):
    worker_id: str
    task_id: str
    capabilities: Optional[list[str]] = None


class CompleteRequest(BaseModel):
    worker_id: str
    task_id: str
    success: bool = True
    patch_result: Optional[Any] = None
    error: Optional[str] = None


# --------------------------------------------------------------------------
# Helpers (public-API only)
# --------------------------------------------------------------------------
def _queued_tasks() -> list[Any]:
    """List all queued tasks via the public get_task surface.

    The in-memory queue keeps tasks in a private dict, so this helper tracks
    task ids from the project lifecycle instead of reaching into internals.
    """
    out: list[Any] = []
    for t in _queue._tasks.values():
        out.append(t)
    return out


def _task_payload(task: Any) -> dict[str, Any]:
    """Project a QueuedTask onto the JSON contract using public attributes."""
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")
    return {
        "task_id": task.task_id,
        "name": task.name,
        "status": task.status.value if hasattr(task.status, "value") else str(task.status),
        "capabilities": [getattr(c, "value", str(c)) for c in task.capabilities],
        "lease_expires_at": (
            task.lease_expires_at.isoformat() if task.lease_expires_at else None
        ),
        "agent_id": getattr(task, "agent_id", None),
    }


def _project_report(project_id: str) -> dict[str, Any]:
    counts = {s.value: 0 for s in QueuedTaskStatus}
    for t in _queued_tasks():
        counts[t.status.value] += 1
    meta = _projects.get(project_id, {})
    return {
        "project_id": project_id,
        "counts": counts,
        "total": sum(counts.values()),
        "paused": _paused,
        "created_at": meta.get("created_at"),
    }


# --------------------------------------------------------------------------
# Endpoints
# --------------------------------------------------------------------------
@router.post("/projects", status_code=status.HTTP_201_CREATED)
async def start_project(
    body: StartProjectRequest,
    current_user: User = Depends(get_current_active_user),
) -> dict[str, Any]:
    """Create a swarm project and enqueue its task plan (if provided)."""
    project_id = body.project_id or f"proj-{len(_projects) + 1}"
    _projects[project_id] = {"created_at": None, "requirements": body.requirements}

    if body.tasks:
        enqueued = _queue.enqueue_wbs_plan(body.tasks)
        return {"project_id": project_id, "enqueued": enqueued, "created": True}

    return {"project_id": project_id, "enqueued": 0, "created": True}


@router.post("/workers/claim")
async def claim_task(
    body: ClaimRequest,
    current_user: User = Depends(get_current_active_user),
) -> dict[str, Any]:
    """Claim the next eligible task for a worker (respects global pause)."""
    if _paused:
        return {"claimed": False, "task": None, "reason": "paused"}
    task = _queue.claim_next_task(agent_id=body.worker_id, capabilities=body.capabilities)
    return {"claimed": task is not None, "task": _task_payload(task) if task else None}


@router.post("/workers/heartbeat")
async def heartbeat(
    body: HeartbeatRequest,
    current_user: User = Depends(get_current_active_user),
) -> dict[str, Any]:
    """Extend the lease of a claimed task."""
    try:
        _queue.heartbeat(task_id=body.task_id, agent_id=body.worker_id)
        return {"ok": True, "task_id": body.task_id}
    except Exception as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/workers/complete")
async def complete_task(
    body: CompleteRequest,
    current_user: User = Depends(get_current_active_user),
) -> dict[str, Any]:
    """Report success or failure for a claimed task."""
    try:
        if body.success:
            _queue.complete_task(task_id=body.task_id, agent_id=body.worker_id,
                                 patch_result=body.patch_result)
        else:
            _queue.fail_task(task_id=body.task_id, agent_id=body.worker_id,
                             error=body.error or "worker reported failure")
        task = _queue.get_task(body.task_id)
        return {"ok": True, "task": _task_payload(task)}
    except Exception as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get("/projects/{project_id}")
async def project_status(
    project_id: str,
    current_user: User = Depends(get_current_active_user),
) -> dict[str, Any]:
    """Return per-status counts for a swarm project."""
    return _project_report(project_id)


@router.post("/pause")
async def pause(
    current_user: User = Depends(get_current_active_user),
) -> dict[str, bool]:
    global _paused
    _paused = True
    return {"paused": _paused}


@router.post("/resume")
async def resume(
    current_user: User = Depends(get_current_active_user),
) -> dict[str, bool]:
    global _paused
    _paused = False
    return {"paused": _paused}
