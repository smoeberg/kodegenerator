"""Immutable contracts for deterministic and independent bot evaluation."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from phase4.council.configuration import IndependenceLevel

_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_SHA = re.compile(r"^[a-f0-9]{64}$")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _digest(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(
            value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
        ).encode()
    ).hexdigest()


def _identity(name: str, value: str) -> None:
    if not _ID.fullmatch(value):
        raise ValueError(f"{name} must be a canonical identifier")


def _sha(name: str, value: str) -> None:
    if not _SHA.fullmatch(value):
        raise ValueError(f"{name} must be a SHA-256 fingerprint")


def _aware(value: datetime) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("timestamps must be timezone-aware")


class EvaluationOutcome(str, Enum):
    PASS = "pass"
    FAIL = "fail"
    REWORK = "rework"


@dataclass(frozen=True)
class RubricCriterion:
    criterion_id: str
    description: str
    weight: float
    semantic: bool = False
    hard_failure: bool = False

    def __post_init__(self) -> None:
        _identity("criterion_id", self.criterion_id)
        if not self.description.strip() or self.description != self.description.strip():
            raise ValueError("criterion description must be canonical text")
        if not 0 < self.weight <= 1:
            raise ValueError("criterion weight must be in (0, 1]")
        if self.semantic and self.hard_failure:
            raise ValueError("semantic criteria cannot be deterministic hard failures")


@dataclass(frozen=True)
class EvaluationRubric:
    organization_id: str
    rubric_id: str
    version: int
    subject_classes: tuple[str, ...]
    criteria: tuple[RubricCriterion, ...]
    pass_threshold: float
    independence_level: IndependenceLevel
    created_at: datetime = field(default_factory=_now)

    def __post_init__(self) -> None:
        _identity("organization_id", self.organization_id)
        _identity("rubric_id", self.rubric_id)
        if self.version < 1 or not 0 <= self.pass_threshold <= 1:
            raise ValueError("rubric version or threshold is invalid")
        if (
            self.subject_classes != tuple(sorted(set(self.subject_classes)))
            or not self.subject_classes
        ):
            raise ValueError("subject classes must be sorted, unique, and non-empty")
        ids = tuple(item.criterion_id for item in self.criteria)
        if not ids or len(ids) != len(set(ids)):
            raise ValueError("rubric criteria must be non-empty and unique")
        _aware(self.created_at)

    @property
    def fingerprint(self) -> str:
        return _digest(
            {
                "organization_id": self.organization_id,
                "rubric_id": self.rubric_id,
                "version": self.version,
                "subject_classes": self.subject_classes,
                "criteria": [item.__dict__ for item in self.criteria],
                "pass_threshold": self.pass_threshold,
                "independence_level": self.independence_level.value,
            }
        )


@dataclass(frozen=True)
class EvaluationAssignmentSnapshot:
    assignment_id: str
    bot_profile_id: str
    connection_id: str
    deployment_id: str
    model_family: str
    provider_adapter: str
    brand: str
    prompt_version: str

    def __post_init__(self) -> None:
        _sha("assignment_id", self.assignment_id)
        for name, value in self.__dict__.items():
            if name != "assignment_id" and (
                not value.strip() or value != value.strip()
            ):
                raise ValueError(f"{name} must be canonical text")


def validate_independence(
    producer: EvaluationAssignmentSnapshot,
    evaluator: EvaluationAssignmentSnapshot,
    level: IndependenceLevel,
) -> None:
    dimensions = {
        IndependenceLevel.PROFILE: ("bot_profile_id",),
        IndependenceLevel.CONNECTION: ("bot_profile_id", "connection_id"),
        IndependenceLevel.DEPLOYMENT: (
            "bot_profile_id",
            "connection_id",
            "deployment_id",
        ),
        IndependenceLevel.MODEL_FAMILY: (
            "bot_profile_id",
            "connection_id",
            "model_family",
        ),
        IndependenceLevel.PROVIDER: (
            "bot_profile_id",
            "connection_id",
            "provider_adapter",
        ),
        IndependenceLevel.BRAND: (
            "bot_profile_id",
            "connection_id",
            "provider_adapter",
            "brand",
        ),
    }[level]
    collisions = [
        name
        for name in dimensions
        if getattr(producer, name) == getattr(evaluator, name)
    ]
    if collisions:
        raise ValueError("evaluator independence violated: " + ", ".join(collisions))


@dataclass(frozen=True)
class EvaluationCheck:
    criterion_id: str
    passed: bool
    score: float
    evidence: tuple[str, ...]

    def __post_init__(self) -> None:
        _identity("criterion_id", self.criterion_id)
        if not 0 <= self.score <= 1 or not self.evidence:
            raise ValueError("check score or evidence is invalid")


@dataclass(frozen=True)
class EvaluationRecord:
    organization_id: str
    evaluation_id: str
    subject_id: str
    subject_class: str
    subject_fingerprint: str
    rubric_id: str
    rubric_version: int
    rubric_fingerprint: str
    base_sha: str
    producer: EvaluationAssignmentSnapshot
    evaluator: EvaluationAssignmentSnapshot | None
    checks: tuple[EvaluationCheck, ...]
    semantic_evidence: tuple[str, ...]
    hard_failures: tuple[str, ...]
    outcome: EvaluationOutcome
    score: float
    confidence: float
    provenance: tuple[tuple[str, Any], ...]
    created_at: datetime = field(default_factory=_now)

    def __post_init__(self) -> None:
        _identity("organization_id", self.organization_id)
        _identity("subject_id", self.subject_id)
        _identity("rubric_id", self.rubric_id)
        _sha("subject_fingerprint", self.subject_fingerprint)
        _sha("rubric_fingerprint", self.rubric_fingerprint)
        if not re.fullmatch(r"[a-f0-9]{40}", self.base_sha):
            raise ValueError("base_sha must be an exact Git SHA-1")
        if not 0 <= self.score <= 1 or not 0 <= self.confidence <= 1:
            raise ValueError("score and confidence must be normalized")
        if self.hard_failures and self.outcome is EvaluationOutcome.PASS:
            raise ValueError("hard failures cannot produce a passing evaluation")
        _aware(self.created_at)
        expected = self.content_fingerprint
        if self.evaluation_id != expected:
            raise ValueError("evaluation_id must equal the content fingerprint")

    @property
    def content_fingerprint(self) -> str:
        return evaluation_fingerprint(
            organization_id=self.organization_id,
            subject_id=self.subject_id,
            subject_class=self.subject_class,
            subject_fingerprint=self.subject_fingerprint,
            rubric_id=self.rubric_id,
            rubric_version=self.rubric_version,
            rubric_fingerprint=self.rubric_fingerprint,
            base_sha=self.base_sha,
            producer=self.producer,
            evaluator=self.evaluator,
            checks=self.checks,
            semantic_evidence=self.semantic_evidence,
            hard_failures=self.hard_failures,
            outcome=self.outcome,
            score=self.score,
            confidence=self.confidence,
            provenance=self.provenance,
        )


def evaluation_fingerprint(**values: Any) -> str:
    """Build the content identity before constructing an immutable record."""
    return _digest(
        {
            "organization_id": values["organization_id"],
            "subject_id": values["subject_id"],
            "subject_class": values["subject_class"],
            "subject_fingerprint": values["subject_fingerprint"],
            "rubric": [
                values["rubric_id"],
                values["rubric_version"],
                values["rubric_fingerprint"],
            ],
            "base_sha": values["base_sha"],
            "producer": values["producer"].__dict__,
            "evaluator": None
            if values["evaluator"] is None
            else values["evaluator"].__dict__,
            "checks": [item.__dict__ for item in values["checks"]],
            "semantic_evidence": values["semantic_evidence"],
            "hard_failures": values["hard_failures"],
            "outcome": values["outcome"].value,
            "score": values["score"],
            "confidence": values["confidence"],
            "provenance": values["provenance"],
        }
    )
