"""HTTP contracts for governed onboarding-intent declaration."""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from generation.project_spec import ProjectDefinition
from phase4.onboarding import OnboardingPurpose


class OnboardingIntentDeclareRequest(BaseModel):
    """Client-owned semantic input; trusted identity/tenant fields are forbidden."""

    model_config = ConfigDict(extra="forbid")

    command_id: str = Field(min_length=1, max_length=128)
    source_repository: str = Field(min_length=1, max_length=128)
    purpose: OnboardingPurpose
    rationale: str = Field(min_length=1)
    target_stack: ProjectDefinition | None = None
    supersedes_intent_id: str | None = Field(
        default=None,
        pattern=r"^[0-9a-f]{64}$",
    )


class OnboardingIntentResponse(BaseModel):
    intent_id: str
    content_fingerprint: str
    organization_id: str
    source_repository: str
    purpose: OnboardingPurpose
    rationale: str
    target_stack: ProjectDefinition | None = None
    supersedes_intent_id: str | None = None
    declared_by: str
    declared_at: datetime


class OnboardingIntentCommandResponse(BaseModel):
    command_id: str
    replayed: bool
    intent: OnboardingIntentResponse
