"""Semantic evaluator adapter using the governed structured-LLM boundary."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from phase4.verification.evaluation import EvaluationRubric
from phase4.verification.evaluation_coordinator import SemanticEvaluation

from .governed_llm import GovernedLLMRequest, GovernedLLMRuntime


class GovernedLocalEvaluator:
    """Treat LibreChat/OpenAI-compatible local models as ordinary providers."""

    def __init__(
        self,
        runtime: GovernedLLMRuntime,
        *,
        organization_id: str,
        actor_id: str,
        model: str,
    ) -> None:
        self._runtime = runtime
        self._organization_id = organization_id
        self._actor_id = actor_id
        self._model = model

    def evaluate(self, *, subject: Any, rubric: EvaluationRubric) -> SemanticEvaluation:
        semantic_ids = [item.criterion_id for item in rubric.criteria if item.semantic]
        subject_fingerprint = hashlib.sha256(
            json.dumps(
                subject, sort_keys=True, separators=(",", ":"), default=str
            ).encode()
        ).hexdigest()
        result = self._runtime.generate(
            GovernedLLMRequest(
                organization_id=self._organization_id,
                actor_id=self._actor_id,
                idempotency_key=(
                    f"evaluation:{rubric.fingerprint}:{subject_fingerprint}"
                ),
                purpose="independent_semantic_evaluation",
                model=self._model,
                instructions=(
                    "Evaluate only the supplied semantic rubric criteria. "
                    "Never override deterministic checks."
                ),
                untrusted_input={"subject": subject, "criteria": semantic_ids},
                output_schema={
                    "type": "object",
                    "required": ["scores", "evidence", "confidence"],
                    "properties": {
                        "scores": {"type": "object"},
                        "evidence": {"type": "array", "items": {"type": "string"}},
                        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                    },
                },
                max_input_tokens=8_000,
                max_output_tokens=2_000,
            )
        )
        scores = result.value.get("scores")
        evidence = result.value.get("evidence")
        confidence = result.value.get("confidence")
        if (
            not isinstance(scores, dict)
            or not isinstance(evidence, list)
            or not isinstance(confidence, (int, float))
        ):
            raise ValueError("governed evaluator returned malformed semantic evidence")
        return SemanticEvaluation(
            scores=tuple(
                sorted((str(key), float(value)) for key, value in scores.items())
            ),
            evidence=tuple(str(item) for item in evidence),
            confidence=float(confidence),
            provenance=tuple(sorted(result.provenance.__dict__.items())),
        )
