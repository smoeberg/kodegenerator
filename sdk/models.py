"""Type-safe response models and SDK exceptions."""
from __future__ import annotations

from typing import Any
from pydantic import BaseModel, ConfigDict, Field


class TaskResponse(BaseModel):
    """Response returned after submitting a task."""
    model_config = ConfigDict(extra="allow")
    task_id: str
    project_id: str | None = None
    status: str


class ProjectStatus(BaseModel):
    """Current project status."""
    model_config = ConfigDict(extra="allow")
    project_id: str
    status: str
    tasks: list[dict[str, Any]] = Field(default_factory=list)


class SwarmEvent(BaseModel):
    """A streamed swarm event."""
    model_config = ConfigDict(extra="allow")
    event: str
    data: dict[str, Any] = Field(default_factory=dict)


class GateApproval(BaseModel):
    """Gate approval response."""
    model_config = ConfigDict(extra="allow")
    approved: bool
    gate_id: str | None = None


class KodegenAPIError(Exception):
    """Base exception for API failures."""
    def __init__(self, message: str, *, status_code: int | None = None, response: Any = None) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.response = response


class QuotaExceededError(KodegenAPIError):
    """Raised when the API quota is exhausted."""


class ApprovalRequiredError(KodegenAPIError):
    """Raised when an operation requires gate approval."""
