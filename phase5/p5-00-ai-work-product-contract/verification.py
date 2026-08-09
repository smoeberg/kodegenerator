"""Independent verification boundary for P5-00."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable, Mapping, Tuple

from .models import AIWorkProductContract, CriterionResult, RepositoryState, VerificationDecision, WorkProductSubmission


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
        actual_repository_state: RepositoryState | None = None,
        predicates: Mapping[str, Predicate] | None = None,
        governed_evidence_fingerprints: Mapping[str, str] | None = None,
        now: datetime | None = None,
    ) -> VerificationDecision:
        """Evaluate every criterion and return the authoritative decision.

        ``actual_repository_state`` and artifact fingerprints are supplied by
        the governed verification runtime. They are compared with the exact
        repository snapshot claimed at submission time, so post-submission
        repository changes cannot be silently accepted.
        """
        if submission.contract_fingerprint != contract.contract_fingerprint:
            raise VerificationError("contract fingerprint mismatch")
        submitted_repo = submission.repository_state
        if not submitted_repo.repository or not submitted_repo.revision:
            raise VerificationError("repository identity/revision missing")
        if not submitted_repo.tree_fingerprint:
            raise VerificationError("repository tree fingerprint missing")
        if actual_repository_state is not None:
            if actual_repository_state != submitted_repo:
                raise VerificationError("repository state changed after submission")

        declared = {a.artifact_id: a for a in contract.required_artifacts}
        submitted_ids = [a.artifact_id for a in submission.artifacts]
        if len(submitted_ids) != len(set(submitted_ids)):
            raise VerificationError("submission artifact IDs must be unique")
        submitted = {a.artifact_id: a for a in submission.artifacts}
        unknown = set(submitted) - set(declared)
        if unknown:
            raise VerificationError(f"submission contains undeclared artifacts: {sorted(unknown)}")

        results: list[CriterionResult] = []
        for artifact_id, requirement in declared.items():
            candidate = submitted.get(artifact_id)
            actual = repository_artifact_fingerprints.get(artifact_id) if candidate else None
            if candidate is None:
                if requirement.required:
                    results.append(CriterionResult(
                        criterion_id=f"artifact:{artifact_id}", passed=False, evidence_ids=(),
                        verifier=self.verifier_id, reason="required artifact missing from submission",
                    ))
                continue
            if candidate.artifact_type != requirement.artifact_type or candidate.location != requirement.location:
                results.append(CriterionResult(
                    criterion_id=f"artifact:{artifact_id}", passed=False, evidence_ids=(),
                    verifier=self.verifier_id, reason="submitted artifact metadata does not match contract",
                ))
                continue
            if actual is None or actual != candidate.content_fingerprint:
                results.append(CriterionResult(
                    criterion_id=f"artifact:{artifact_id}", passed=False, evidence_ids=(),
                    verifier=self.verifier_id, reason="artifact fingerprint missing or does not match repository state",
                ))

        evidence_ids = [f.evidence_id for f in governed_facts]
        if len(evidence_ids) != len(set(evidence_ids)):
            raise VerificationError("governed evidence IDs must be unique")
        if any(not f.evidence_id or not f.payload_fingerprint or not f.source for f in governed_facts):
            raise VerificationError("governed evidence must have identity, source and fingerprint")
        declared_criteria = {criterion.criterion_id for criterion in contract.acceptance_criteria}
        unknown_criteria = {fact.criterion_id for fact in governed_facts} - declared_criteria
        if unknown_criteria:
            raise VerificationError(f"governed evidence references undeclared criteria: {sorted(unknown_criteria)}")
        evidence_fingerprints = governed_evidence_fingerprints or {}
        for fact in governed_facts:
            actual = evidence_fingerprints.get(fact.evidence_id)
            if actual is None or actual != fact.payload_fingerprint:
                raise VerificationError(f"governed evidence fingerprint mismatch: {fact.evidence_id}")

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

        mandatory_results = [
            r for r in results
            if not r.criterion_id.startswith("artifact:")
            and next(c for c in contract.acceptance_criteria if c.criterion_id == r.criterion_id).mandatory
        ]
        artifact_results = [r for r in results if r.criterion_id.startswith("artifact:")]
        passed = bool(results) and all(r.passed for r in artifact_results) and all(r.passed for r in mandatory_results)
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
