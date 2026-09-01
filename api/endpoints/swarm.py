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

import hashlib
import os
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from api.auth import User, get_current_active_user
from services.swarm_task_queue import QueuedTaskStatus, SwarmTaskQueue

router = APIRouter(prefix="/api/v1/swarm", tags=["swarm"])

# Single in-process swarm queue behind the control plane (main contract).
_queue: SwarmTaskQueue = SwarmTaskQueue()
_projects: dict[str, dict[str, Any]] = {}
_paused: bool = False


def project_access_allowed(project_id: str, username: str) -> bool:
    """Return whether ``username`` owns the in-process swarm project."""
    project = _projects.get(project_id)
    return project is not None and project.get("owner_id") == username


def require_project_access(project_id: str, username: str) -> dict[str, Any]:
    """Resolve project metadata without revealing another user's project."""
    project = _projects.get(project_id)
    if project is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Project not found"
        )
    if project.get("owner_id") != username:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Project access denied"
        )
    return project


# --------------------------------------------------------------------------
# Schemas
# --------------------------------------------------------------------------
class StartProjectRequest(BaseModel):
    project_id: str | None = None
    requirements: dict[str, Any] = Field(default_factory=dict)
    tasks: list[dict[str, Any]] = Field(default_factory=list)


class ClaimRequest(BaseModel):
    capabilities: list[str] = Field(default_factory=list)


class HeartbeatRequest(BaseModel):
    task_id: str
    capabilities: list[str] | None = None


class CompleteRequest(BaseModel):
    task_id: str
    success: bool = True
    patch_result: Any | None = None
    error: str | None = None


# --------------------------------------------------------------------------
# Helpers (public-API only)
# --------------------------------------------------------------------------
def _queue_backend():
    if os.environ.get("DOR_QUEUE_BACKEND") == "database":
        from api.dependencies import get_dor
        from runtime.pipeline_registry import get_pipeline_registry

        return get_pipeline_registry(get_dor()).queue
    return _queue


def _http_worker_id(username: str) -> str:
    """Derive bounded claim ownership from authenticated identity."""
    return "http:" + hashlib.sha256(username.encode()).hexdigest()


def _queued_tasks() -> list[Any]:
    """List all queued tasks via the public get_task surface.

    The in-memory queue keeps tasks in a private dict, so this helper tracks
    task ids from the project lifecycle instead of reaching into internals.
    """
    queue = _queue_backend()
    list_tasks = getattr(queue, "list_tasks", None)
    if callable(list_tasks):
        return list_tasks()
    return list(queue._tasks.values())


def _task_payload(task: Any) -> dict[str, Any]:
    """Project a QueuedTask onto the JSON contract using public attributes."""
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")
    return {
        "task_id": task.task_id,
        "name": task.name,
        "status": task.status.value
        if hasattr(task.status, "value")
        else str(task.status),
        "capabilities": [getattr(c, "value", str(c)) for c in task.capabilities],
        "lease_expires_at": (
            task.lease_expires_at.isoformat() if task.lease_expires_at else None
        ),
        "agent_id": getattr(task, "agent_id", None),
    }


def _project_report(project_id: str) -> dict[str, Any]:
    counts = {s.value: 0 for s in QueuedTaskStatus}
    for t in _queued_tasks():
        if t.metadata.get("project_id") == project_id:
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
    if project_id in _projects:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="Project already exists"
        )
    _projects[project_id] = {
        "created_at": None,
        "requirements": body.requirements,
        "owner_id": current_user.username,
    }

    if body.tasks:
        tasks = [
            {
                **task,
                "metadata": {
                    **dict(task.get("metadata", {})),
                    "project_id": project_id,
                },
            }
            for task in body.tasks
        ]
        enqueued = _queue_backend().enqueue_wbs_plan(tasks)
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
    task = _queue_backend().claim_next_task(
        agent_id=_http_worker_id(current_user.username), capabilities=body.capabilities
    )
    return {"claimed": task is not None, "task": _task_payload(task) if task else None}


@router.post("/workers/heartbeat")
async def heartbeat(
    body: HeartbeatRequest,
    current_user: User = Depends(get_current_active_user),
) -> dict[str, Any]:
    """Extend the lease of a claimed task."""
    try:
        _queue_backend().heartbeat(
            task_id=body.task_id, agent_id=_http_worker_id(current_user.username)
        )
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
            _queue_backend().complete_task(
                task_id=body.task_id,
                agent_id=_http_worker_id(current_user.username),
                patch_result=body.patch_result,
            )
        else:
            _queue_backend().fail_task(
                task_id=body.task_id,
                agent_id=_http_worker_id(current_user.username),
                error=body.error or "worker reported failure",
            )
        task = _queue_backend().get_task(body.task_id)
        return {"ok": True, "task": _task_payload(task)}
    except Exception as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get("/projects/{project_id}")
async def project_status(
    project_id: str,
    current_user: User = Depends(get_current_active_user),
) -> dict[str, Any]:
    """Return per-status counts for a swarm project."""
    require_project_access(project_id, current_user.username)
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
