"""Independent verification boundary for P5-00.

The engine consumes repository facts supplied by a governed verifier. It never
promotes agent claims to authoritative evidence and never accepts an agent
supplied PASS/FAIL as a decision.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable, Mapping, Tuple

from .models import (
    AIWorkProductContract,
    CriterionResult,
    VerificationDecision,
    WorkProductSubmission,
)
from .fingerprinting import fingerprint


class VerificationError(ValueError):
    """Raised when a submission cannot be verified safely."""


@dataclass(frozen=True)
class GovernedFact:
    """Fact produced by the verification runtime, not by the agent."""
    evidence_id: str
    criterion_id: str
    payload: object
    source: str


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
        now: datetime | None = None,
    ) -> VerificationDecision:
        """Evaluate every criterion and return the authoritative decision.

        `repository_artifact_fingerprints` and `governed_facts` must originate
        from the verification runtime. Agent candidate evidence is intentionally
        ignored as proof.
        """
        if submission.contract_fingerprint != contract.contract_fingerprint:
            raise VerificationError("contract fingerprint mismatch")
        if not submission.repository_state.repository:
            raise VerificationError("repository identity missing")
        if not submission.repository_state.revision:
            raise VerificationError("repository revision missing")
        if not submission.repository_state.tree_fingerprint:
            raise VerificationError("repository tree fingerprint missing")

        required = {a.artifact_id: a for a in contract.required_artifacts if a.required}
        submitted = {a.artifact_id: a for a in submission.artifacts}
        results = []

        for artifact_id, requirement in required.items():
            candidate = submitted.get(artifact_id)
            if candidate is None:
                results.append(CriterionResult(
                    criterion_id=f"artifact:{artifact_id}", passed=False,
                    evidence_ids=(), verifier=self.verifier_id,
                    reason="required artifact missing from submission",
                ))
                continue
            actual = repository_artifact_fingerprints.get(artifact_id)
            if actual is None or actual != candidate.content_fingerprint:
                results.append(CriterionResult(
                    criterion_id=f"artifact:{artifact_id}", passed=False,
                    evidence_ids=(), verifier=self.verifier_id,
                    reason="artifact fingerprint missing or does not match repository state",
                ))

        facts_by_criterion = {}
        for fact in governed_facts:
            facts_by_criterion.setdefault(fact.criterion_id, []).append(fact)

        for criterion in contract.acceptance_criteria:
            facts = facts_by_criterion.get(criterion.criterion_id, [])
            if not facts:
                results.append(CriterionResult(
                    criterion_id=criterion.criterion_id, passed=False,
                    evidence_ids=(), verifier=self.verifier_id,
                    reason="no governed evidence for criterion",
                ))
                continue
            # Predicate interpretation belongs to the governed verifier. This
            # primitive deliberately does not execute agent-supplied code.
            passed = all(bool(f.payload) for f in facts)
            results.append(CriterionResult(
                criterion_id=criterion.criterion_id,
                passed=passed,
                evidence_ids=tuple(f.evidence_id for f in facts),
                verifier=self.verifier_id,
                reason="governed evidence satisfied predicate" if passed else "governed evidence did not satisfy predicate",
            ))

        passed = all(r.passed for r in results) and bool(results)
        timestamp = now or datetime.now(timezone.utc)
        return VerificationDecision(
            decision_id=decision_id,
            submission_id=submission.submission_id,
            contract_fingerprint=contract.contract_fingerprint,
            verifier=self.verifier_id,
            passed=passed,
            criterion_results=tuple(results),
            decided_at=timestamp,
        )
