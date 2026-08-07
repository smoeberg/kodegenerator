# api/endpoints/tasks.py
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, status

from api.dependencies import get_dor
from api.models import TaskCreate, TaskResponse
from domain.task import Task, TaskStatus
from runtime.core import DORRuntime

router = APIRouter(prefix="/tasks", tags=["tasks"])


def _response(task: Task, dor: DORRuntime) -> TaskResponse:
    workflow = dor.db_adapter.get_workflow(task.workflow_id) if task.workflow_id else None
    actor = dor.db_adapter.get_actor(task.assigned_actor_id) if task.assigned_actor_id else None
    return TaskResponse(id=task.id, name=task.name, description=task.description, status=task.status, priority=task.priority, workflow_id=task.workflow_id, workflow=workflow.to_dict() if workflow else None, assigned_actor_id=task.assigned_actor_id, assigned_actor=actor.to_dict() if actor else None, dependencies=task.dependencies, input_artifacts=task.input_artifacts, output_artifacts=task.output_artifacts, metadata=task.metadata, created_at=task.created_at, updated_at=task.updated_at)


@router.post("/", response_model=TaskResponse, status_code=status.HTTP_201_CREATED)
def create_task(task: TaskCreate, dor: DORRuntime = Depends(get_dor)):
    workflow = dor.db_adapter.get_workflow(task.workflow_id) if task.workflow_id else None
    if task.workflow_id and not workflow:
        raise HTTPException(status_code=404, detail="Workflow not found")
    assigned_actor = dor.db_adapter.get_actor(task.assigned_actor_id) if task.assigned_actor_id else None
    db_task = Task(id=task.id, name=task.name, description=task.description, status=task.status, priority=task.priority, workflow_id=task.workflow_id, assigned_actor=assigned_actor, dependencies=task.dependencies, input_artifacts=task.input_artifacts, output_artifacts=task.output_artifacts, metadata=task.metadata)
    task_model = dor.db_adapter.create_task(db_task)
    dor.workflow_engine.task_scheduler.schedule_task(db_task)
    return _response(task_model, dor)


@router.get("/{task_id}", response_model=TaskResponse)
def get_task(task_id: str, dor: DORRuntime = Depends(get_dor)):
    task = dor.db_adapter.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    return _response(task, dor)


@router.get("/", response_model=List[TaskResponse])
def get_tasks(workflow_id: Optional[str] = None, actor_id: Optional[str] = None, status: Optional[str] = None, dor: DORRuntime = Depends(get_dor)):
    if workflow_id:
        tasks = dor.db_adapter.uow.task.get_by_workflow(workflow_id)
    elif actor_id:
        tasks = dor.db_adapter.uow.task.get_assigned_tasks(actor_id)
    else:
        tasks = dor.db_adapter.uow.task.get_all()
    if status:
        try:
            expected = TaskStatus(status)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="Invalid task status") from exc
        tasks = [task for task in tasks if task.status == expected]
    return [_response(task, dor) for task in tasks]


@router.post("/{task_id}/assign", response_model=TaskResponse)
def assign_task(task_id: str, actor_id: str, dor: DORRuntime = Depends(get_dor)):
    task = dor.db_adapter.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    actor = dor.db_adapter.get_actor(actor_id)
    if not actor:
        raise HTTPException(status_code=404, detail="Actor not found")
    dor.workflow_engine.task_scheduler.assign_task(task, actor)
    task_model = dor.db_adapter.uow.task.get(task_id)
    task_model.assigned_actor_id = actor_id
    task_model.status = TaskStatus.ASSIGNED
    dor.db_adapter.uow.commit()
    return _response(dor.db_adapter.get_task(task_id), dor)


@router.post("/{task_id}/complete", response_model=TaskResponse)
def complete_task(task_id: str, output_artifacts: List[str], dor: DORRuntime = Depends(get_dor)):
    task = dor.db_adapter.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    dor.workflow_engine.task_scheduler.complete_task(task_id, output_artifacts)
    task_model = dor.db_adapter.uow.task.get(task_id)
    task_model.status = TaskStatus.COMPLETED
    task_model.output_artifacts = output_artifacts
    dor.db_adapter.uow.commit()
    return _response(dor.db_adapter.get_task(task_id), dor)
