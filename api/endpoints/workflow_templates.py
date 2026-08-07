# api/endpoints/workflow_templates.py
from typing import List

from fastapi import APIRouter, Depends, HTTPException

from api.dependencies import get_dor
from api.models import WorkflowTemplateResponse
from runtime.core import DORRuntime

router = APIRouter(prefix="/workflow-templates", tags=["workflow_templates"])


def _response(template) -> WorkflowTemplateResponse:
    return WorkflowTemplateResponse(id=template.id, name=template.name, description=template.description, required_capabilities=template.required_capabilities, default_priority=template.default_priority, states=[state.to_dict() for state in template.states], transitions=[transition.to_dict() for transition in template.transitions], gates=[gate.to_dict() for gate in template.gates], default_tasks=template.default_tasks, created_at=template.created_at, updated_at=template.updated_at)


@router.get("/", response_model=List[WorkflowTemplateResponse])
def get_workflow_templates(dor: DORRuntime = Depends(get_dor)):
    return [_response(template) for template in dor.get_workflow_templates()]


@router.get("/{template_id}", response_model=WorkflowTemplateResponse)
def get_workflow_template(template_id: str, dor: DORRuntime = Depends(get_dor)):
    template = dor.get_workflow_template(template_id)
    if not template:
        raise HTTPException(status_code=404, detail="WorkflowTemplate not found")
    return _response(template)
