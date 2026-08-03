# api/endpoints/workflow_templates.py
from fastapi import APIRouter, Depends, HTTPException, status
from typing import List
from api.models import WorkflowTemplateResponse
from infrastructure.database.dor_runtime_db import DORRuntimeDB

router = APIRouter(prefix="/workflow-templates", tags=["workflow_templates"])

@router.get("/", response_model=List[WorkflowTemplateResponse])
def get_workflow_templates(
    dor: DORRuntimeDB = Depends(get_dor)
):
    """Hent alle Workflow Templates."""
    templates = dor.get_workflow_templates()
    return [
        WorkflowTemplateResponse(
            id=t.id,
            name=t.name,
            description=t.description,
            required_capabilities=t.required_capabilities,
            default_priority=t.default_priority,
            states=[s.to_dict() for s in t.states],
            transitions=[t.to_dict() for t in t.transitions],
            gates=[g.to_dict() for g in t.gates],
            default_tasks=t.default_tasks,
            created_at=t.created_at,
            updated_at=t.updated_at
        )
        for t in templates
    ]

@router.get("/{template_id}", response_model=WorkflowTemplateResponse)
def get_workflow_template(
    template_id: str,
    dor: DORRuntimeDB = Depends(get_dor)
):
    """Hent en Workflow Template ud fra ID."""
    template = dor.get_workflow_template(template_id)
    if not template:
        raise HTTPException(status_code=404, detail="WorkflowTemplate not found")
    return WorkflowTemplateResponse(
        id=template.id,
        name=template.name,
        description=template.description,
        required_capabilities=template.required_capabilities,
        default_priority=template.default_priority,
        states=[s.to_dict() for s in template.states],
        transitions=[t.to_dict() for t in template.transitions],
        gates=[g.to_dict() for g in template.gates],
        default_tasks=template.default_tasks,
        created_at=template.created_at,
        updated_at=template.updated_at
    )
