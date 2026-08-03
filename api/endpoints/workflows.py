# api/endpoints/workflows.py
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, status

from api.dependencies import get_dor
from api.models import WorkflowCreate, WorkflowResponse
from domain.workflow import Workflow, WorkflowState
from infrastructure.database.dor_runtime_db import DORRuntimeDB

router = APIRouter(prefix="/workflows", tags=["workflows"])


def _response(workflow: Workflow, dor: DORRuntimeDB) -> WorkflowResponse:
    return WorkflowResponse(
        id=workflow.id,
        name=workflow.name,
        description=workflow.description,
        current_state=workflow.current_state.name if workflow.current_state else None,
        states=[s.to_dict() for s in workflow.states],
        transitions=[t.to_dict() for t in workflow.transitions],
        gates=[g.to_dict() for g in workflow.gates],
        intent=workflow.intent.to_dict() if workflow.intent else None,
        tasks=[t.to_dict() for t in dor.db_adapter.uow.task.get_by_workflow(workflow.id)],
        artifacts=[a.to_dict() for a in dor.db_adapter.uow.artifact.get_by_workflow(workflow.id)],
        created_at=workflow.created_at,
        updated_at=workflow.updated_at,
    )


@router.post("/", response_model=WorkflowResponse, status_code=status.HTTP_201_CREATED)
def create_workflow(
    workflow: WorkflowCreate,
    dor: DORRuntimeDB = Depends(get_dor),
):
    """Opret et nyt Workflow."""
    intent = dor.db_adapter.get_intent(workflow.intent_id) if workflow.intent_id else None
    if workflow.intent_id and not intent:
        raise HTTPException(status_code=404, detail="Intent not found")

    if workflow.template_id:
        template = dor.get_workflow_template(workflow.template_id)
        if not template:
            raise HTTPException(status_code=404, detail="WorkflowTemplate not found")
        db_workflow = template.instantiate(
            workflow_id=workflow.id,
            intent_id=workflow.intent_id,
            organization_id=dor.organization.id,
        )
    else:
        db_workflow = Workflow(
            id=workflow.id,
            name=workflow.name,
            description=workflow.description,
            intent=intent,
            organization=dor.organization,
        )

    workflow_model = dor.db_adapter.create_workflow(db_workflow)
    dor.workflow_engine.add_workflow(db_workflow)
    return _response(workflow_model, dor)


@router.get("/{workflow_id}", response_model=WorkflowResponse)
def get_workflow(workflow_id: str, dor: DORRuntimeDB = Depends(get_dor)):
    """Hent et Workflow ud fra ID."""
    workflow = dor.db_adapter.get_workflow(workflow_id)
    if not workflow:
        raise HTTPException(status_code=404, detail="Workflow not found")
    return _response(workflow, dor)


@router.get("/", response_model=List[WorkflowResponse])
def get_workflows(
    intent_id: Optional[str] = None,
    dor: DORRuntimeDB = Depends(get_dor),
):
    """Hent alle Workflows, eventuelt filtreret efter Intent."""
    workflows = dor.db_adapter.uow.workflow.get_all()
    if intent_id:
        workflows = [wf for wf in workflows if wf.intent_id == intent_id]
    return [_response(dor.db_adapter.get_workflow(wf.id), dor) for wf in workflows]


@router.post("/{workflow_id}/transition", response_model=WorkflowResponse)
def transition_workflow(
    workflow_id: str,
    new_state: str,
    actor_id: str,
    dor: DORRuntimeDB = Depends(get_dor),
):
    """Skift tilstand for et Workflow."""
    workflow = dor.db_adapter.get_workflow(workflow_id)
    if not workflow:
        raise HTTPException(status_code=404, detail="Workflow not found")

    actor = dor.db_adapter.get_actor(actor_id)
    if not actor:
        raise HTTPException(status_code=404, detail="Actor not found")

    try:
        new_state_enum = WorkflowState(new_state)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid workflow state") from exc

    if not dor.workflow_engine.transition_workflow(workflow_id, new_state_enum, actor):
        raise HTTPException(status_code=400, detail="Transition failed")

    workflow_model = dor.db_adapter.uow.workflow.get(workflow_id)
    workflow_model.current_state = new_state_enum
    dor.db_adapter.uow.commit()
    return _response(dor.db_adapter.get_workflow(workflow_id), dor)
