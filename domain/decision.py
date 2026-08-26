"""First-class governed decision domain models."""
from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Optional
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator


class DecisionCategory(str, Enum):
    TECHNICAL = "TECHNICAL"
    FUNCTIONAL = "FUNCTIONAL"
    ARCHITECTURE = "ARCHITECTURE"
    RELEASE = "RELEASE"


class DecisionStatus(str, Enum):
    PROPOSED = "PROPOSED"
    HUMAN_REQUIRED = "HUMAN_REQUIRED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class RiskLevel(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class DecisionAlternative(BaseModel):
    """A concrete option the controller can select."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    key: str = Field(min_length=1, max_length=32)
    title: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=4000)
    pros: list[str] = Field(default_factory=list)
    cons: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    risk_level: RiskLevel = RiskLevel.MEDIUM

    @field_validator("key")
    @classmethod
    def key_must_be_normalized(cls, value: str) -> str:
        value = value.strip().upper()
        if not value:
            raise ValueError("alternative key must not be empty")
        return value


class AgentVote(BaseModel):
    """An agent's independent recommendation and confidence."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    agent_id: str = Field(min_length=1, max_length=256)
    selected_alternative: str = Field(min_length=1, max_length=32)
    argument: str = Field(min_length=1, max_length=8000)
    confidence: float = Field(ge=0.0, le=1.0)
    risk_level: RiskLevel = RiskLevel.MEDIUM
    provenance_id: str = Field(min_length=1, max_length=256)


class HumanDecision(BaseModel):
    """Immutable representation of the controller's resolution."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    selected_alternative: str = Field(min_length=1, max_length=32)
    rationale: str = Field(min_length=1, max_length=8000)
    decided_by: str = Field(min_length=1, max_length=256)
    decided_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class Decision(BaseModel):
    """A governed crossroad at which autonomous execution may need to stop."""

    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    decision_id: str = Field(default_factory=lambda: str(uuid4()), min_length=1)
    project_id: str = Field(min_length=1, max_length=256)
    category: DecisionCategory
    question: str = Field(min_length=1, max_length=8000)
    alternatives: list[DecisionAlternative] = Field(min_length=2)
    agent_votes: list[AgentVote] = Field(default_factory=list)
    status: DecisionStatus = DecisionStatus.PROPOSED
    human_decision: Optional[HumanDecision] = None
    provenance_id: str = Field(min_length=1, max_length=256)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    resolved_at: Optional[datetime] = None
    risk_level: RiskLevel = RiskLevel.MEDIUM

    @field_validator("alternatives")
    @classmethod
    def unique_alternative_keys(cls, value: list[DecisionAlternative]) -> list[DecisionAlternative]:
        keys = [item.key for item in value]
        if len(keys) != len(set(keys)):
            raise ValueError("alternative keys must be unique")
        return value

    def resolve(self, human_decision: HumanDecision, *, approved: bool = True) -> None:
        if self.status is not DecisionStatus.HUMAN_REQUIRED:
            raise ValueError("only HUMAN_REQUIRED decisions can be resolved")
        valid_keys = {alternative.key for alternative in self.alternatives}
        if human_decision.selected_alternative.upper() not in valid_keys:
            raise ValueError("selected alternative does not belong to this decision")
        self.human_decision = human_decision.model_copy(
            update={"selected_alternative": human_decision.selected_alternative.upper()}
        )
        self.status = DecisionStatus.APPROVED if approved else DecisionStatus.REJECTED
        self.resolved_at = datetime.now(timezone.utc)
