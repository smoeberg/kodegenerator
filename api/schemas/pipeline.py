"""Validated public contracts for the pipeline HTTP API."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class StartPipelineRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    requirements_yaml: str = Field(min_length=1)
    project_name: str | None = None


class TaskStatusResponse(BaseModel):
    id: str
    task_type: str
    status: str


class PipelineStatusResponse(BaseModel):
    workflow_id: str
    current_state: str
    state_name: str
    tasks: list[TaskStatusResponse]
    context: dict[str, Any] = Field(default_factory=dict)


class PipelineListItem(BaseModel):
    workflow_id: str
    name: str
    current_state: str
    project_name: str | None = None
    created_at: str
    updated_at: str


class PipelineListResponse(BaseModel):
    items: list[PipelineListItem]
    total: int
    limit: int
    offset: int


class PipelineWorkerClaimRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    worker_id: str = Field(min_length=1, max_length=128)
    organization_id: str = Field(min_length=1, max_length=128)
    capabilities: list[str] = Field(default_factory=list)


class PipelineWorkerCompleteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    worker_id: str = Field(min_length=1, max_length=128)
    task_id: str = Field(min_length=1, max_length=256)
    organization_id: str = Field(min_length=1, max_length=128)
    success: bool = True
    result: dict[str, Any] | None = None
    error: str | None = None
