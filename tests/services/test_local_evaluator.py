from types import SimpleNamespace

import pytest

from phase4.council.configuration import IndependenceLevel
from phase4.verification.evaluation import EvaluationRubric, RubricCriterion
from services.local_evaluator import GovernedLocalEvaluator


def rubric() -> EvaluationRubric:
    return EvaluationRubric(
        organization_id="org-1",
        rubric_id="semantic-v1",
        version=1,
        subject_classes=("candidate",),
        criteria=(RubricCriterion("quality", "Code quality", 1.0, semantic=True),),
        pass_threshold=0.8,
        independence_level=IndependenceLevel.CONNECTION,
    )


class Runtime:
    def __init__(self, value) -> None:
        self.value = value
        self.requests = []

    def generate(self, request):
        self.requests.append(request)
        provenance = SimpleNamespace(
            provider="openai-compatible",
            model="local-model",
            request_id="request-1",
            prompt_fingerprint="a" * 64,
            output_fingerprint="b" * 64,
            prompt_tokens=10,
            completion_tokens=5,
            total_tokens=15,
        )
        return SimpleNamespace(value=self.value, provenance=provenance)


def test_local_provider_is_governed_and_subject_bound() -> None:
    runtime = Runtime(
        {"scores": {"quality": 0.9}, "evidence": ["review-1"], "confidence": 0.8}
    )
    evaluator = GovernedLocalEvaluator(
        runtime, organization_id="org-1", actor_id="assignment-1", model="local-model"
    )
    result = evaluator.evaluate(subject={"patch": "one"}, rubric=rubric())
    evaluator.evaluate(subject={"patch": "two"}, rubric=rubric())
    assert result.scores == (("quality", 0.9),)
    assert runtime.requests[0].purpose == "independent_semantic_evaluation"
    assert runtime.requests[0].idempotency_key != runtime.requests[1].idempotency_key


def test_malformed_local_evidence_fails_closed() -> None:
    evaluator = GovernedLocalEvaluator(
        Runtime({"scores": [], "evidence": [], "confidence": "high"}),
        organization_id="org-1",
        actor_id="assignment-1",
        model="local-model",
    )
    with pytest.raises(ValueError, match="malformed"):
        evaluator.evaluate(subject={"patch": "one"}, rubric=rubric())
