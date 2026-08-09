"""Independent verification boundary for P5-00."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable, Mapping, Tuple

from .models import AIWorkProductContract, CriterionResult, VerificationDecision, WorkProductSubmission


class VerificationError(ValueError):
    """Raised when a submission cannot be verified safely."""


@dataclass(frozen=True)
class GovernedFact:
    """Fact produced by the verification runtime, not by the agent."""
    evidence_id: str
    criterion_id: str
    payload: object
    source: str
    payload_fingerprint: str


Predicate = Callable[[Tuple[GovernedFact, ...]], bool]


class VerificationEngine:
    """P3-20-facing, fail-closed verification engine."""

    def __init__(self, verifier_id: str = "p3-20") -> None:
        if verifier_id != "p3-20":
            raise VerificationError("verification authority must be p3-20")
        self.verifier_id = verifier_id

    def verify(
        self,
        contract: AIWorkProductContract,
        submission: WorkProductSubmission,
        governed_facts: Tuple[GovernedFact, ...],
        repository_artifact_fingerprints: Mapping[str, str],
        *,
        decision_id: str,
        predicates: Mapping[str, Predicate] | None = None,
        now: datetime | None = None,
    ) -> VerificationDecision:
        """Evaluate every criterion and return the authoritative decision."""
        if submission.contract_fingerprint != contract.contract_fingerprint:
            raise VerificationError("contract fingerprint mismatch")
        if not submission.repository_state.repository or not submission.repository_state.revision:
            raise VerificationError("repository identity/revision missing")
        if not submission.repository_state.tree_fingerprint:
            raise VerificationError("repository tree fingerprint missing")

        required = {a.artifact_id: a for a in contract.required_artifacts if a.required}
        submitted = {a.artifact_id: a for a in submission.artifacts}
        unknown = set(submitted) - {a.artifact_id for a in contract.required_artifacts}
        if unknown:
            raise VerificationError(f"submission contains undeclared artifacts: {sorted(unknown)}")

        results = []
        for artifact_id in required:
            candidate = submitted.get(artifact_id)
            actual = repository_artifact_fingerprints.get(artifact_id) if candidate else None
            if candidate is None:
                results.append(CriterionResult(
                    criterion_id=f"artifact:{artifact_id}", passed=False, evidence_ids=(),
                    verifier=self.verifier_id, reason="required artifact missing from submission",
                ))
            elif actual is None or actual != candidate.content_fingerprint:
                results.append(CriterionResult(
                    criterion_id=f"artifact:{artifact_id}", passed=False, evidence_ids=(),
                    verifier=self.verifier_id, reason="artifact fingerprint missing or does not match repository state",
                ))

        facts_by_criterion: dict[str, list[GovernedFact]] = {}
        for fact in governed_facts:
            facts_by_criterion.setdefault(fact.criterion_id, []).append(fact)

        predicates = predicates or {}
        for criterion in contract.acceptance_criteria:
            facts = tuple(facts_by_criterion.get(criterion.criterion_id, ()))
            if not facts:
                results.append(CriterionResult(
                    criterion_id=criterion.criterion_id, passed=False, evidence_ids=(),
                    verifier=self.verifier_id, reason="no governed evidence for criterion",
                ))
                continue
            if any(f.source != criterion.evidence_source for f in facts):
                results.append(CriterionResult(
                    criterion_id=criterion.criterion_id, passed=False,
                    evidence_ids=tuple(f.evidence_id for f in facts), verifier=self.verifier_id,
                    reason="governed evidence source does not match contract",
                ))
                continue
            predicate = predicates.get(criterion.criterion_id)
            if predicate is None:
                results.append(CriterionResult(
                    criterion_id=criterion.criterion_id, passed=False,
                    evidence_ids=tuple(f.evidence_id for f in facts), verifier=self.verifier_id,
                    reason="no governed predicate registered for criterion",
                ))
                continue
            passed = bool(predicate(facts))
            results.append(CriterionResult(
                criterion_id=criterion.criterion_id, passed=passed,
                evidence_ids=tuple(f.evidence_id for f in facts), verifier=self.verifier_id,
                reason="governed predicate passed" if passed else "governed predicate failed",
            ))

        criterion_ids = [c.criterion_id for c in contract.acceptance_criteria]
        returned_ids = [r.criterion_id for r in results if not r.criterion_id.startswith("artifact:")]
        if returned_ids != criterion_ids:
            raise VerificationError("criterion evaluation is incomplete or duplicated")

        passed = bool(results) and all(r.passed for r in results)
        timestamp = now or datetime.now(timezone.utc)
        return VerificationDecision(
            decision_id=decision_id,
            submission_id=submission.submission_id,
            submission_fingerprint=submission.submission_fingerprint,
            contract_fingerprint=contract.contract_fingerprint,
            verifier=self.verifier_id,
            passed=passed,
            criterion_results=tuple(results),
            decided_at=timestamp,
        )
