"""Epistemic models for evidence-based hypothesis reasoning."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional
from uuid import uuid4

from pydantic import BaseModel, Field


class HypothesisStatus(str, Enum):
    PROPOSED = "PROPOSED"
    ACTIVE = "ACTIVE"
    TESTING = "TESTING"
    SUPPORTED = "SUPPORTED"
    WEAKENED = "WEAKENED"
    REJECTED = "REJECTED"
    SUPERSEDED = "SUPERSEDED"


class EvidenceType(str, Enum):
    SUPPORTING = "SUPPORTING"
    CONTRADICTING = "CONTRADICTING"
    OBSERVATION = "OBSERVATION"


class Evidence(BaseModel):
    evidence_id: str = Field(default_factory=lambda: str(uuid4()))
    hypothesis_id: str
    evidence_type: EvidenceType
    weight: float = Field(default=0.2, ge=0.0, le=1.0)
    source: str
    description: str
    metadata: Dict[str, Any] = Field(default_factory=dict)
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class Hypothesis(BaseModel):
    hypothesis_id: str = Field(default_factory=lambda: str(uuid4()))
    task_id: str
    statement: str
    status: HypothesisStatus = HypothesisStatus.PROPOSED
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    supporting_evidence: List[Evidence] = Field(default_factory=list)
    contradicting_evidence: List[Evidence] = Field(default_factory=list)
    alternatives: List[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
