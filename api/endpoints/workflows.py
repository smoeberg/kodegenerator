"""Canonical workflow API backed exclusively by DORRuntime."""
from typing import List

from fastapi import APIRouter, Depends, HTTPException, status

from api.auth import User, get_current_active_user
from api.dependencies import get_dor
from api.models import WorkflowCreate, WorkflowResponse, WorkflowTransitionRequest
from domain.principal import Principal
from domain.workflow import Workflow, WorkflowState
from runtime.context import ContextError
from runtime.core import CommandAuthorizationError, DORRuntime, NotFoundError
from runtime.commands import AdvanceWorkflowCommand

router = APIRouter(prefix="/workflows", tags=["workflows"])


def _response(workflow: Workflow) -> WorkflowResponse:
    def to_dict(value):
        if hasattr(value, "to_dict"):
            return value.to_dict()
        if hasattr(value, "__dict__"):
            return {key: item for key, item in value.__dict__.items() if not key.startswith("_")}
        return str(value)

    current_state = workflow.current_state
    current_name = None
    if current_state is not None:
        state_name = getattr(current_state, "name", current_state)
        current_name = getattr(state_name, "name", state_name)
        current_name = str(current_name).lower()

    return WorkflowResponse(
        id=workflow.id,
        name=workflow.name,
        description=workflow.description,
        current_state=current_name,
        states=[to_dict(item) for item in workflow.states],
        transitions=[to_dict(item) for item in workflow.transitions],
        gates=[to_dict(item) for item in workflow.gates],
        intent=to_dict(workflow.intent) if workflow.intent else None,
        tasks=[],
        artifacts=[],
        created_at=workflow.created_at,
        updated_at=workflow.updated_at,
    )


def _context(dor: DORRuntime, current_user: User, organization_id: str):
    principal = Principal(id=current_user.username, type="user", metadata={"username": current_user.username})
    try:
        return dor.establish_context(principal=principal, organization_id=organization_id, actor_id=current_user.username)
    except (ContextError, NotFoundError) as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc


@router.post("/", response_model=WorkflowResponse, status_code=status.HTTP_201_CREATED)
def create_workflow(
    workflow: WorkflowCreate,
    current_user: User = Depends(get_current_active_user),
    dor: DORRuntime = Depends(get_dor),
):
    """Create a workflow through the canonical organization-scoped runtime."""
    if workflow.intent_id or workflow.template_id:
        raise HTTPException(status_code=400, detail="intent_id and template_id are not supported by the canonical P3-13 runtime API")
    organization_id = getattr(workflow, "organization_id", None)
    if not organization_id:
        raise HTTPException(status_code=422, detail="organization_id is required")
    context = _context(dor, current_user, organization_id)
    try:
        created = dor.create_workflow(context, name=workflow.name, description=workflow.description or "")
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _response(created)


@router.get("/", response_model=List[WorkflowResponse])
def get_workflows(
    organization_id: str,
    current_user: User = Depends(get_current_active_user),
    dor: DORRuntime = Depends(get_dor),
):
    context = _context(dor, current_user, organization_id)
    return [_response(workflow) for workflow in dor.list_workflows(context)]


@router.get("/{workflow_id}", response_model=WorkflowResponse)
def get_workflow(
    workflow_id: str,
    organization_id: str,
    current_user: User = Depends(get_current_active_user),
    dor: DORRuntime = Depends(get_dor),
):
    context = _context(dor, current_user, organization_id)
    try:
        return _response(dor.get_workflow(context, workflow_id))
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail="Workflow not found") from exc


@router.post("/{workflow_id}/transition", response_model=WorkflowResponse)
def transition_workflow(
    workflow_id: str,
    request: WorkflowTransitionRequest,
    current_user: User = Depends(get_current_active_user),
    dor: DORRuntime = Depends(get_dor),
):
    """Execute a workflow transition through the single canonical command boundary."""
    principal = Principal(id=current_user.username, type="user", metadata={"username": current_user.username})
    try:
        context = dor.establish_context(principal=principal, organization_id=request.organization_id, actor_id=current_user.username)
        target_state = WorkflowState[request.new_state.name.upper()]
        command = AdvanceWorkflowCommand(command_id=request.command_id, organization_id=request.organization_id, workflow_id=workflow_id, target_state=target_state)
        result = dor.execute_command(context, command)
    except CommandAuthorizationError as exc:
        raise HTTPException(status_code=403, detail={"error": "authorization_denied", "reason_code": exc.decision.reason_code, "reason": exc.decision.reason, "workflow_id": workflow_id}) from exc
    except (ContextError, NotFoundError) as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except KeyError as exc:
        raise HTTPException(status_code=400, detail=f"Invalid state: {request.new_state}") from exc
    return _response(result.workflow)
