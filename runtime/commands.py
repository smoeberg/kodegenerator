"""Command contracts for the Phase 2 DOR command runtime."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from domain.workflow import WorkflowState


class CommandConflictError(RuntimeError):
    """Raised when a command ID is reused with different command data."""


@dataclass(frozen=True)
class AdvanceWorkflowCommand:
    """Request one workflow state transition within an organization."""

    command_id: str
    organization_id: str
    workflow_id: str
    target_state: WorkflowState

    @property
    def payload(self) -> dict[str, Any]:
        return {
            "command_type": type(self).__name__,
            "organization_id": self.organization_id,
            "workflow_id": self.workflow_id,
            "target_state": self.target_state.name,
        }


@dataclass(frozen=True)
class CommandResult:
    """Result returned from successful or previously completed commands."""

    command_id: str
    workflow: Any
