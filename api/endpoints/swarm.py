"""REST control plane for the DOR swarm factory."""
from __future__ import annotations
from datetime import datetime, timezone
from typing import Any, Optional
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from api.auth import User, get_current_active_user
from services.swarm_task_queue import SwarmTaskQueue

router=APIRouter(prefix="/api/v1/swarm",tags=["swarm"])
_queue=SwarmTaskQueue(); _projects={}; _paused=False

class TaskIn(BaseModel):
    task_id: Optional[str]=None; name: str="task"; dependencies:list[str]=[]; capabilities:list[str]=[]; priority:int=0
class ProjectRequest(BaseModel):
    project_id: Optional[str]=None; requirements: dict[str,Any]=Field(default_factory=dict); tasks:list[TaskIn]=[]
class WorkerRequest(BaseModel):
    worker_id:str=Field(min_length=1); capabilities:list[str]=[]
class HeartbeatRequest(WorkerRequest): task_id:str
class CompleteRequest(WorkerRequest): task_id:str; patch_result:Any=None; error:Optional[str]=None; retry:bool=True
class PauseRequest(BaseModel): project_id:Optional[str]=None

def _task(t):
    return {"task_id":t.task_id,"name":t.name,"dependencies":list(t.dependencies),"capabilities":list(t.capabilities),"priority":t.priority,"status":t.status,"worker_id":t.agent_id,"lease_expires_at":t.lease_expires_at,"retry_count":t.retry_count,"error":t.error}
def _report(pid):
    tasks=_queue.tasks_for_project(pid); counts={}
    for t in tasks:counts[t.status]=counts.get(t.status,0)+1
    return {"project_id":pid,"paused":_paused,"total_tasks":len(tasks),"counts":counts,"tasks":[_task(t) for t in tasks],"updated_at":datetime.now(timezone.utc)}

@router.post("/projects",status_code=status.HTTP_201_CREATED)
def start_project(req:ProjectRequest,current_user:User=Depends(get_current_active_user)):
    pid=req.project_id or f"project-{datetime.now(timezone.utc).timestamp()}"
    if pid in _projects:raise HTTPException(409,"project already exists")
    tasks=[]
    for i,t in enumerate(req.tasks):
        tasks.append({"id":t.task_id or f"{pid}-task-{i+1}","name":t.name,"dependencies":t.dependencies,"capabilities":t.capabilities,"priority":t.priority,"metadata":{"project_id":pid}})
    if not tasks:
        tasks=[{"id":f"{pid}-bootstrap","name":"bootstrap swarm project","capabilities":[],"metadata":{"project_id":pid}}]
    plan={"id":pid,"tasks":tasks};_queue.enqueue_wbs_plan(plan);_projects[pid]={"requirements":req.requirements,"created_by":current_user.username}
    return {"project_id":pid,"status":"STARTED","run_report":_report(pid)}

@router.post("/workers/claim")
def claim(req:WorkerRequest,current_user:User=Depends(get_current_active_user)):
    if _paused:return {"task":None,"paused":True}
    t=_queue.claim_next_task(req.worker_id,req.capabilities)
    return {"task":_task(t) if t else None}

@router.post("/workers/heartbeat")
def heartbeat(req:HeartbeatRequest,current_user:User=Depends(get_current_active_user)):
    try:t=_queue.heartbeat(req.task_id,req.worker_id)
    except KeyError:raise HTTPException(404,"task not found")
    except (PermissionError,RuntimeError) as e:raise HTTPException(409,str(e))
    return {"task":_task(t)}

@router.post("/workers/complete")
def complete(req:CompleteRequest,current_user:User=Depends(get_current_active_user)):
    try:
        t=_queue.fail_task(req.task_id,req.worker_id,req.error,req.retry) if req.error is not None else _queue.complete_task(req.task_id,req.worker_id,req.patch_result)
    except KeyError:raise HTTPException(404,"task not found")
    except (PermissionError,RuntimeError) as e:raise HTTPException(409,str(e))
    return {"task":_task(t)}

@router.get("/projects/{project_id}")
def project_status(project_id:str,current_user:User=Depends(get_current_active_user)):
    if project_id not in _projects:raise HTTPException(404,"project not found")
    return _report(project_id)

@router.post("/pause")
def pause(req:PauseRequest,current_user:User=Depends(get_current_active_user)):
    global _paused;_paused=True;return {"status":"PAUSED","project_id":req.project_id}

@router.post("/resume")
def resume(req:PauseRequest,current_user:User=Depends(get_current_active_user)):
    global _paused;_paused=False;return {"status":"RESUMED","project_id":req.project_id}
