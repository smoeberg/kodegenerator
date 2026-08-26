"""Council specialist agent domain definitions."""
from __future__ import annotations

from enum import Enum
from typing import Any
from pydantic import BaseModel, Field


class AgentRole(str, Enum):
    """Specialized roles participating in the Deliberation Council."""
    ARCHITECT = "architect"
    PM = "pm"
    QA = "qa"
    SECURITY = "security"
    DEVELOPER = "developer"
    COORDINATOR = "coordinator"


class AgentPosition(BaseModel):
    """An individual specialist agent's evaluation and proposal on a topic."""
    agent_id: str
    role: AgentRole
    preferred_alternative: str
    confidence: float = Field(ge=0.0, le=1.0)
    reasoning: str
    identified_risks: list[str] = Field(default_factory=list)
    veto: bool = False
    metadata: dict[str, Any] = Field(default_factory=dict)


class DeliberationAgenda(BaseModel):
    """The subject and context framed for council deliberation."""
    agenda_id: str
    project_id: str
    topic: str
    description: str
    options: list[str]
    context_packets: dict[str, Any] = Field(default_factory=dict)
