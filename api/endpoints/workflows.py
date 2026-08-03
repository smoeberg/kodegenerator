# api/endpoints/workflows.py
from fastapi import APIRouter, Depends, HTTPException, status
from typing import List
from api.models import WorkflowCreate, WorkflowResponse
from infrastructure.database.dor_runtime_db import DORRuntimeDB
from domain.workflow import Workflow, WorkflowState

router = APIRouter(prefix="/workflows", tags=["workflows"])

@router.post("/", response_model=WorkflowResponse, status_code=status.HTTP_201_CREATED)
def create_workflow(
    workflow: WorkflowCreate,
    dor: DORRuntimeDB = Depends(get_dor)
):
    """Opret et nyt Workflow."""
    intent = dor.db_adapter.get_intent(workflow.intent_id) if workflow.intent_id else None
    if workflow.intent_id and not intent:
        raise HTTPException(status_code=404, detail="Intent not found")

    # Hvis template_id er angivet, brug Workflow Template
    if workflow.template_id:
        template = dor.get_workflow_template(workflow.template_id)
        if not template:
            raise HTTPException(status_code=404, detail="WorkflowTemplate not found")
        db_workflow = template.instantiate(
            workflow_id=workflow.id,
            intent_id=workflow.intent_id,
            organization_id=dor.organization.id
        )
    else:
        # Opret et tomt Workflow
        db_workflow = Workflow(
            id=workflow.id,
            name=workflow.name,
            description=workflow.description,
            intent=intent,
            organization=dor.organization
        )

    # Gem Workflow i databasen
    workflow_model = dor.db_adapter.create_workflow(db_workflow)

    # Tilføj Workflow til WorkflowEngine
    dor.workflow_engine.add_workflow(db_workflow)

    return WorkflowResponse(
        id=workflow_model.id,
        name=workflow_model.name,
        description=workflow_model.description,
        current_state=workflow_model.current_state,
        states=[s.to_dict() for s in db_workflow.states],
        transitions=[t.to_dict() for t in db_workflow.transitions],
        gates=[g.to_dict() for g in db_workflow.gates],
        intent=intent.to_dict() if intent else None,
        tasks=[],
        artifacts=[],
        created_at=workflow_model.created_at,
        updated_at=workflow_model.updated_at
    )

@router.get("/{workflow_id}", response_model=WorkflowResponse)
def get_workflow(
    workflow_id: str,
    dor: DORRuntimeDB = Depends(get_dor)
):
    """Hent et Workflow ud fra ID."""
    workflow = dor.db_adapter.get_workflow(workflow_id)
    if not workflow:
        raise HTTPException(status_code=404, detail="Workflow not found")

    # Hent Tasks og Artifacts for Workflow
    tasks = dor.db_adapter.uow.task.get_by_workflow(workflow_id)
    artifacts = dor.db_adapter.uow.artifact.get_by_workflow(workflow_id)

    return WorkflowResponse(
        id=workflow.id,
        name=workflow.name,
        description=workflow.description,
        current_state=workflow.current_state.name if workflow.current_state else None,
        states=[s.to_dict() for s in workflow.states],
        transitions=[t.to_dict() for t in workflow.transitions],
        gates=[g.to_dict() for g in workflow.gates],
        intent=workflow.intent.to_dict() if workflow.intent else None,
        tasks=[t.to_dict() for t in tasks],
        artifacts=[a.to_dict() for a in artifacts],
        created_at=workflow.created_at,
        updated_at=workflow.updated_at
    )

@router.get("/", response_model=List[WorkflowResponse])
def get_workflows(
    intent_id: Optional[str] = None,
    dor: DORRuntimeDB = Depends(get_dor)
):
    """Hent alle Workflows (filtreret efter Intent)."""
    if intent_id:
        workflows = [dor.db_adapter.get_workflow(wf.id) for wf in dor.db_adapter.uow.workflow.get_all() if wf.intent_id == intent_id]
    else:
        workflows = [dor.db_adapter.get_workflow(wf.id) for wf in dor.db_adapter.uow.workflow.get_all()]

    return [
        WorkflowResponse(
            id=wf.id,
            name=wf.name,
            description=wf.description,
            current_state=wf.current_state.name if wf.current_state else None,
            states=[s.to_dict() for s in wf.states],
            transitions=[t.to_dict() for t in wf.transitions],
            gates=[g.to_dict() for g in wf.gates],
            intent=wf.intent.to_dict() if wf.intent else None,
            tasks=[t.to_dict() for t in dor.db_adapter.uow.task.get_by_workflow(wf.id)],
            artifacts=[a.to_dict() for a in dor.db_adapter.uow.artifact.get_by_workflow(wf.id)],
            created_at=wf.created_at,
            updated_at=wf.updated_at
        )
        for wf in workflows
    ]

@router.post("/{workflow_id}/transition", response_model=WorkflowResponse)
def transition_workflow(
    workflow_id: str,
    new_state: WorkflowStateEnum,
    actor_id: str,
    dor: DORRuntimeDB = Depends(get_dor)
):
    """Skift tilstand for et Workflow."""
    workflow = dor.db_adapter.get_workflow(workflow_id)
    if not workflow:
        raise HTTPException(status_code=404, detail="Workflow not found")

    actor = dor.db_adapter.get_actor(actor_id)
    if not actor:
        raise HTTPException(status_code=404, detail="Actor not found")

    # Konverter new_state til WorkflowState
    new_state_enum = WorkflowState(new_state.value)

    # Udfør transition
    success = dor.workflow_engine.transition_workflow(
        workflow_id,
        new_state_enum,
        actor
    )
    if not success:
        raise HTTPException(status_code=400, detail="Transition failed")

    # Opdater Workflow i databasen
    workflow_model = dor.db_adapter.uow.workflow.get(workflow_id)
    workflow_model.current_state = new_state_enum.value
    dor.db_adapter.uow.commit()

    # Returner opdateret Workflow
    updated_workflow = dor.db_adapter.get_workflow(workflow_id)
    return WorkflowResponse(
        id=updated_workflow.id,
        name=updated_workflow.name,
        description=updated_workflow.description,
        current_state=updated_workflow.current_state.name if updated_workflow.current_state else None,
        states=[s.to_dict() for s in updated_workflow.states],
        transitions=[t.to_dict() for t in updated_workflow.transitions],
        gates=[g.to_dict() for g in updated_workflow.gates],
        intent=updated_workflow.intent.to_dict() if updated_workflow.intent else None,
        tasks=[t.to_dict() for t in dor.db_adapter.uow.task.get_by_workflow(workflow_id)],
        artifacts=[a.to_dict() for a in dor.db_adapter.uow.artifact.get_by_workflow(workflow_id)],
        created_at=updated_workflow.created_at,
        updated_at=updated_workflow.updated_at
    )
