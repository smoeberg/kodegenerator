"""Domain models for runtime adaptation, strategy fingerprinting, and anti-tube triggers."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional
from uuid import uuid4

from pydantic import BaseModel, Field


class FailureCategory(str, Enum):
    SAME_FAILURE = "SAME_FAILURE"
    REGRESSION = "REGRESSION"
    ENVIRONMENT_FAILURE = "ENVIRONMENT_FAILURE"
    POLICY_DENIAL = "POLICY_DENIAL"
    UNKNOWN = "UNKNOWN"


class AdaptationAction(str, Enum):
    RETRY = "RETRY"
    PIVOT_REQUEST = "PIVOT_REQUEST"
    HALT_ENVIRONMENT = "HALT_ENVIRONMENT"
    POLICY_ESCALATION = "POLICY_ESCALATION"


class ExecutionFailure(BaseModel):
    failure_id: str = Field(default_factory=lambda: str(uuid4()))
    task_id: str
    error_type: str
    error_message: str
    stack_trace: Optional[str] = None
    exit_code: Optional[int] = None
    failed_tests: List[str] = Field(default_factory=list)
    newly_failed_tests: List[str] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class StrategyFingerprint(BaseModel):
    fingerprint_id: str = Field(default_factory=lambda: str(uuid4()))
    hypothesis_id: str
    affected_files: List[str] = Field(default_factory=list)
    change_pattern: str
    summary_hash: str
    metadata: Dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class AdaptationResult(BaseModel):
    action: AdaptationAction
    category: FailureCategory
    fingerprint_hash: str
    hypothesis_id: str
    consecutive_same_failures: int
    reason: str
    pivot_required: bool = False
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
