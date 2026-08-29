# api/schemas/pipeline.py

from typing import Any

from pydantic import BaseModel, ConfigDict


class StartPipelineRequest(BaseModel):
    requirements_yaml: str
    project_name: str | None = None


class TaskStatusResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    task_type: str
    status: str

class PipelineStatusResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    workflow_id: str
    current_state: str
    project_name: str | None
    created_at: str
    updated_at: str
    tasks: list[TaskStatusResponse]
    error: str | None
    context: dict[str, Any]

class PipelineListItem(BaseModel):
    workflow_id: str
    name: str
    current_state: str
    project_name: str | None
    created_at: str
    updated_at: str

class PipelineListResponse(BaseModel):
    items: list[PipelineListItem]
    total: int
    limit: int
    offset: int
