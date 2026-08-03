# api/endpoints/tasks.py
from fastapi import APIRouter, Depends, HTTPException, status
from typing import List
from api.models import TaskCreate, TaskResponse
from infrastructure.database.dor_runtime_db import DORRuntimeDB
from domain.task import Task, TaskStatus, TaskPriority

router = APIRouter(prefix="/tasks", tags=["tasks"])

@router.post("/", response_model=TaskResponse, status_code=status.HTTP_201_CREATED)
def create_task(
    task: TaskCreate,
    dor: DORRuntimeDB = Depends(get_dor)
):
    """Opret en ny Task."""
    workflow = dor.db_adapter.get_workflow(task.workflow_id) if task.workflow_id else None
    if task.workflow_id and not workflow:
        raise HTTPException(status_code=404, detail="Workflow not found")

    assigned_actor = dor.db_adapter.get_actor(task.assigned_actor_id) if task.assigned_actor_id else None

    db_task = Task(
        id=task.id,
        name=task.name,
        description=task.description,
        status=task.status,
        priority=task.priority,
        workflow_id=task.workflow_id,
        assigned_actor=assigned_actor,
        dependencies=task.dependencies,
        input_artifacts=task.input_artifacts,
        output_artifacts=task.output_artifacts,
        metadata=task.metadata
    )

    # Gem Task i databasen
    task_model = dor.db_adapter.create_task(db_task)

    # Tilføj Task til WorkflowEngine
    dor.workflow_engine.task_scheduler.schedule_task(db_task)

    return TaskResponse(
        id=task_model.id,
        name=task_model.name,
        description=task_model.description,
        status=task_model.status,
        priority=task_model.priority,
        workflow_id=task_model.workflow_id,
        workflow=workflow.to_dict() if workflow else None,
        assigned_actor_id=task_model.assigned_actor_id,
        assigned_actor=assigned_actor.to_dict() if assigned_actor else None,
        dependencies=task_model.dependencies,
        input_artifacts=task_model.input_artifacts,
        output_artifacts=task_model.output_artifacts,
        metadata=task_model.metadata,
        created_at=task_model.created_at,
        updated_at=task_model.updated_at
    )

@router.get("/{task_id}", response_model=TaskResponse)
def get_task(
    task_id: str,
    dor: DORRuntimeDB = Depends(get_dor)
):
    """Hent en Task ud fra ID."""
    task = dor.db_adapter.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    workflow = dor.db_adapter.get_workflow(task.workflow_id) if task.workflow_id else None
    assigned_actor = dor.db_adapter.get_actor(task.assigned_actor_id) if task.assigned_actor_id else None

    return TaskResponse(
        id=task.id,
        name=task.name,
        description=task.description,
        status=task.status,
        priority=task.priority,
        workflow_id=task.workflow_id,
        workflow=workflow.to_dict() if workflow else None,
        assigned_actor_id=task.assigned_actor_id,
        assigned_actor=assigned_actor.to_dict() if assigned_actor else None,
        dependencies=task.dependencies,
        input_artifacts=task.input_artifacts,
        output_artifacts=task.output_artifacts,
        metadata=task.metadata,
        created_at=task.created_at,
        updated_at=task.updated_at
    )

@router.get("/", response_model=List[TaskResponse])
def get_tasks(
    workflow_id: Optional[str] = None,
    actor_id: Optional[str] = None,
    status: Optional[TaskStatusEnum] = None,
    dor: DORRuntimeDB = Depends(get_dor)
):
    """Hent alle Tasks (filtreret efter workflow, actor, status)."""
    if workflow_id:
        tasks = dor.db_adapter.uow.task.get_by_workflow(workflow_id)
    elif actor_id:
        tasks = dor.db_adapter.uow.task.get_assigned_tasks(actor_id)
    else:
        tasks = dor.db_adapter.uow.task.get_all()

    if status:
        tasks = [t for t in tasks if t.status == TaskStatus(status.value)]

    return [
        TaskResponse(
            id=t.id,
            name=t.name,
            description=t.description,
            status=t.status,
            priority=t.priority,
            workflow_id=t.workflow_id,
            workflow=dor.db_adapter.get_workflow(t.workflow_id).to_dict() if t.workflow_id else None,
            assigned_actor_id=t.assigned_actor_id,
            assigned_actor=dor.db_adapter.get_actor(t.assigned_actor_id).to_dict() if t.assigned_actor_id else None,
            dependencies=t.dependencies,
            input_artifacts=t.input_artifacts,
            output_artifacts=t.output_artifacts,
            metadata=t.metadata,
            created_at=t.created_at,
            updated_at=t.updated_at
        )
        for t in tasks
    ]

@router.post("/{task_id}/assign", response_model=TaskResponse)
def assign_task(
    task_id: str,
    actor_id: str,
    dor: DORRuntimeDB = Depends(get_dor)
):
    """Tildel en Task til en Actor."""
    task = dor.db_adapter.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    actor = dor.db_adapter.get_actor(actor_id)
    if not actor:
        raise HTTPException(status_code=404, detail="Actor not found")

    # Tildel Task
    dor.workflow_engine.task_scheduler.assign_task(task, actor)

    # Opdater Task i databasen
    task_model = dor.db_adapter.uow.task.get(task_id)
    task_model.assigned_actor_id = actor_id
    task_model.status = "assigned"
    dor.db_adapter.uow.commit()

    # Returner opdateret Task
    updated_task = dor.db_adapter.get_task(task_id)
    return TaskResponse(
        id=updated_task.id,
        name=updated_task.name,
        description=updated_task.description,
        status=updated_task.status,
        priority=updated_task.priority,
        workflow_id=updated_task.workflow_id,
        workflow=dor.db_adapter.get_workflow(updated_task.workflow_id).to_dict() if updated_task.workflow_id else None,
        assigned_actor_id=updated_task.assigned_actor_id,
        assigned_actor=actor.to_dict(),
        dependencies=updated_task.dependencies,
        input_artifacts=updated_task.input_artifacts,
        output_artifacts=updated_task.output_artifacts,
        metadata=updated_task.metadata,
        created_at=updated_task.created_at,
        updated_at=updated_task.updated_at
    )

@router.post("/{task_id}/complete", response_model=TaskResponse)
def complete_task(
    task_id: str,
    output_artifacts: List[str],
    dor: DORRuntimeDB = Depends(get_dor)
):
    """Markér en Task som færdiggjort."""
    task = dor.db_adapter.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    # Færdiggør Task
    dor.workflow_engine.task_scheduler.complete_task(task_id, output_artifacts)

    # Opdater Task i databasen
    task_model = dor.db_adapter.uow.task.get(task_id)
    task_model.status = "completed"
    task_model.output_artifacts = output_artifacts
    dor.db_adapter.uow.commit()

    # Returner opdateret Task
    updated_task = dor.db_adapter.get_task(task_id)
    return TaskResponse(
        id=updated_task.id,
        name=updated_task.name,
        description=updated_task.description,
        status=updated_task.status,
        priority=updated_task.priority,
        workflow_id=updated_task.workflow_id,
        workflow=dor.db_adapter.get_workflow(updated_task.workflow_id).to_dict() if updated_task.workflow_id else None,
        assigned_actor_id=updated_task.assigned_actor_id,
        assigned_actor=dor.db_adapter.get_actor(updated_task.assigned_actor_id).to_dict() if updated_task.assigned_actor_id else None,
        dependencies=updated_task.dependencies,
        input_artifacts=updated_task.input_artifacts,
        output_artifacts=updated_task.output_artifacts,
        metadata=updated_task.metadata,
        created_at=updated_task.created_at,
        updated_at=updated_task.updated_at
    )
