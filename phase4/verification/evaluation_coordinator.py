"""Fail-closed deterministic-before-semantic evaluation orchestration."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from .evaluation import (
    EvaluationAssignmentSnapshot,
    EvaluationCheck,
    EvaluationOutcome,
    EvaluationRecord,
    EvaluationRubric,
    evaluation_fingerprint,
    validate_independence,
)


class DeterministicEvaluator(Protocol):
    def evaluate(self, subject: Any, criterion_id: str) -> EvaluationCheck: ...


@dataclass(frozen=True)
class SemanticEvaluation:
    scores: tuple[tuple[str, float], ...]
    evidence: tuple[str, ...]
    confidence: float
    provenance: tuple[tuple[str, Any], ...]


class SemanticEvaluator(Protocol):
    def evaluate(
        self, *, subject: Any, rubric: EvaluationRubric
    ) -> SemanticEvaluation: ...


class EvaluationCoordinator:
    def __init__(
        self, deterministic: DeterministicEvaluator, semantic: SemanticEvaluator
    ) -> None:
        self._deterministic = deterministic
        self._semantic = semantic

    def evaluate(
        self,
        *,
        organization_id: str,
        subject_id: str,
        subject_class: str,
        subject_fingerprint: str,
        base_sha: str,
        subject: Any,
        rubric: EvaluationRubric,
        producer: EvaluationAssignmentSnapshot,
        evaluator: EvaluationAssignmentSnapshot,
    ) -> EvaluationRecord:
        if (
            organization_id != rubric.organization_id
            or subject_class not in rubric.subject_classes
        ):
            raise ValueError(
                "rubric is not bound to the subject organization and class"
            )
        validate_independence(producer, evaluator, rubric.independence_level)
        deterministic_criteria = tuple(
            item for item in rubric.criteria if not item.semantic
        )
        checks = tuple(
            self._deterministic.evaluate(subject, item.criterion_id)
            for item in deterministic_criteria
        )
        if tuple(item.criterion_id for item in checks) != tuple(
            item.criterion_id for item in deterministic_criteria
        ):
            raise ValueError(
                "deterministic evaluator returned incomplete or reordered checks"
            )
        hard_ids = {
            item.criterion_id for item in deterministic_criteria if item.hard_failure
        }
        hard_failures = tuple(
            item.criterion_id
            for item in checks
            if item.criterion_id in hard_ids and not item.passed
        )
        semantic_evidence: tuple[str, ...] = ()
        provenance: tuple[tuple[str, Any], ...] = (
            ("semantic_skipped", bool(hard_failures)),
        )
        confidence = 1.0
        semantic_scores: dict[str, float] = {}
        if not hard_failures:
            semantic = self._semantic.evaluate(subject=subject, rubric=rubric)
            semantic_scores = dict(semantic.scores)
            expected = {item.criterion_id for item in rubric.criteria if item.semantic}
            if set(semantic_scores) != expected or not semantic.evidence:
                raise ValueError("semantic evaluation is incomplete")
            semantic_evidence, confidence, provenance = (
                semantic.evidence,
                semantic.confidence,
                semantic.provenance,
            )
        scores = {item.criterion_id: item.score for item in checks} | semantic_scores
        total_weight = sum(item.weight for item in rubric.criteria)
        score = (
            sum(
                item.weight * scores.get(item.criterion_id, 0.0)
                for item in rubric.criteria
            )
            / total_weight
        )
        outcome = (
            EvaluationOutcome.FAIL
            if hard_failures
            else (
                EvaluationOutcome.PASS
                if score >= rubric.pass_threshold
                else EvaluationOutcome.REWORK
            )
        )
        values = dict(
            organization_id=organization_id,
            subject_id=subject_id,
            subject_class=subject_class,
            subject_fingerprint=subject_fingerprint,
            rubric_id=rubric.rubric_id,
            rubric_version=rubric.version,
            rubric_fingerprint=rubric.fingerprint,
            base_sha=base_sha,
            producer=producer,
            evaluator=evaluator,
            checks=checks,
            semantic_evidence=semantic_evidence,
            hard_failures=hard_failures,
            outcome=outcome,
            score=score,
            confidence=confidence,
            provenance=provenance,
        )
        return EvaluationRecord(
            evaluation_id=evaluation_fingerprint(**values), **values
        )
