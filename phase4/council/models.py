"""Domain models for Council deliberation and dispute protocol."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional
from uuid import uuid4

from pydantic import BaseModel, Field

from phase4.epistemics.models import Evidence, Hypothesis


class SessionState(str, Enum):
    OPEN = "OPEN"
    IN_DISPUTE = "IN_DISPUTE"
    DECISION_READY = "DECISION_READY"
    DEADLOCKED = "DEADLOCKED"


class DisputeStatus(str, Enum):
    OPEN = "OPEN"
    RESOLVED = "RESOLVED"
    DISMISSED = "DISMISSED"


class Dispute(BaseModel):
    dispute_id: str = Field(default_factory=lambda: str(uuid4()))
    hypothesis_id: str
    raised_by_agent_id: str
    reason: str
    status: DisputeStatus = DisputeStatus.OPEN
    resolving_evidence: Optional[Evidence] = None
    resolution_note: Optional[str] = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    resolved_at: Optional[datetime] = None


class Vote(BaseModel):
    agent_id: str
    hypothesis_id: str
    approved: bool
    rationale: Optional[str] = None
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
