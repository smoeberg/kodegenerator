from __future__ import annotations

import hashlib

import pytest

from phase4.council.configuration import IndependenceLevel
from phase4.verification.evaluation import (
    EvaluationAssignmentSnapshot,
    EvaluationCheck,
    EvaluationOutcome,
    EvaluationRubric,
    RubricCriterion,
    validate_independence,
)
from phase4.verification.evaluation_coordinator import (
    EvaluationCoordinator,
    SemanticEvaluation,
)


def assignment(
    name: str, *, connection: str | None = None
) -> EvaluationAssignmentSnapshot:
    return EvaluationAssignmentSnapshot(
        assignment_id=hashlib.sha256(name.encode()).hexdigest(),
        bot_profile_id=f"profile-{name}",
        connection_id=connection or f"connection-{name}",
        deployment_id=f"deployment-{name}",
        model_family=f"family-{name}",
        provider_adapter=f"adapter-{name}",
        brand=f"brand-{name}",
        prompt_version="v1",
    )


def rubric(level: IndependenceLevel = IndependenceLevel.CONNECTION) -> EvaluationRubric:
    return EvaluationRubric(
        organization_id="org-1",
        rubric_id="code-review",
        version=1,
        subject_classes=("candidate",),
        pass_threshold=0.8,
        independence_level=level,
        criteria=(
            RubricCriterion("tests", "Required tests pass", 0.7, hard_failure=True),
            RubricCriterion("quality", "Implementation quality", 0.3, semantic=True),
        ),
    )


class Deterministic:
    def __init__(self, passed: bool) -> None:
        self.passed = passed

    def evaluate(self, subject, criterion_id):
        return EvaluationCheck(
            criterion_id, self.passed, 1.0 if self.passed else 0.0, ("attestation-1",)
        )


class Semantic:
    def __init__(self) -> None:
        self.calls = 0

    def evaluate(self, **_kwargs):
        self.calls += 1
        return SemanticEvaluation(
            (("quality", 1.0),), ("review-evidence",), 0.9, (("request_id", "r1"),)
        )


def test_hard_failure_skips_semantic_evaluator() -> None:
    semantic = Semantic()
    result = EvaluationCoordinator(Deterministic(False), semantic).evaluate(
        organization_id="org-1",
        subject_id="candidate-1",
        subject_class="candidate",
        subject_fingerprint="a" * 64,
        base_sha="b" * 40,
        subject={"patch": "unsafe"},
        rubric=rubric(),
        producer=assignment("producer"),
        evaluator=assignment("evaluator"),
    )
    assert result.outcome is EvaluationOutcome.FAIL
    assert result.hard_failures == ("tests",)
    assert semantic.calls == 0


def test_passing_checks_require_complete_semantic_evidence() -> None:
    semantic = Semantic()
    result = EvaluationCoordinator(Deterministic(True), semantic).evaluate(
        organization_id="org-1",
        subject_id="candidate-1",
        subject_class="candidate",
        subject_fingerprint="a" * 64,
        base_sha="b" * 40,
        subject={"patch": "safe"},
        rubric=rubric(),
        producer=assignment("producer"),
        evaluator=assignment("evaluator"),
    )
    assert result.outcome is EvaluationOutcome.PASS
    assert result.evaluation_id == result.content_fingerprint
    assert semantic.calls == 1


def test_independence_rejects_same_connection() -> None:
    with pytest.raises(ValueError, match="connection_id"):
        validate_independence(
            assignment("one", connection="shared"),
            assignment("two", connection="shared"),
            IndependenceLevel.CONNECTION,
        )
