"""Epistemic core data models for hypothesis generation and belief revision."""
from __future__ import annotations

from enum import Enum
from typing import List, Optional
from pydantic import BaseModel, Field


class HypothesisStatus(str, Enum):
    PROPOSED = "proposed"
    ACTIVE = "active"
    TESTING = "testing"
    SUPPORTED = "supported"
    WEAKENED = "weakened"
    REJECTED = "rejected"
    SUPERSEDED = "superseded"


class Evidence(BaseModel):
    evidence_id: str
    source: str
    content: str
    supports: bool  # True if supporting, False if contradicting
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    timestamp: Optional[str] = None


class Hypothesis(BaseModel):
    hypothesis_id: str
    task_id: str
    statement: str
    status: HypothesisStatus = HypothesisStatus.PROPOSED
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    supporting_evidence: List[Evidence] = Field(default_factory=list)
    contradicting_evidence: List[Evidence] = Field(default_factory=list)
    alternatives: List[str] = Field(default_factory=list)
