# api/schemas/pipeline.py

from pydantic import BaseModel
from typing import Optional, List

class StartPipelineRequest(BaseModel):
    requirements_yaml: str
    project_name: Optional[str] = None

class TaskStatusResponse(BaseModel):
    id: str
    type: str
    status: str
    created_at: str
    completed_at: Optional[str]

class PipelineStatusResponse(BaseModel):
    workflow_id: str
    current_state: str
    project_name: Optional[str]
    created_at: str
    updated_at: str
    tasks: List[TaskStatusResponse]
    error: Optional[str]

class PipelineListItem(BaseModel):
    workflow_id: str
    name: str
    current_state: str
    project_name: Optional[str]
    created_at: str
    updated_at: str

class PipelineListResponse(BaseModel):
    items: List[PipelineListItem]
    total: int
    limit: int
    offset: int
