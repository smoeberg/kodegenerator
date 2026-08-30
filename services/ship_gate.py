"""Fail-closed ShipGate: the quality + authority + integrity gate before PR.

The ShipGate sits between verification and publication.  It accepts the
exact artifacts the release boundary needs — a verified claim (knowledge
record state), an authoritative release grant, a tamper-evident audit
chain root, and attested test evidence — and only then delegates to the
existing :class:`services.git_pr_publisher.GitPRPublisher`.

Every input is optional by type but *required* by policy: the gate fails
closed unless each required artifact is present, verified, and bound to the
patch being shipped.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from phase4.authority.grants import VerifiedAuthorityGrant
from phase4.contracts import KnowledgeRecord, KnowledgeState
from phase6.execution.audit_harness import AuditHarness, ChainIntegrityError
from services.git_pr_publisher import GitPRPublisher
from services.github_pr_contracts import (
    PatchInfo,
    PRMetadata,
    PRResult,
)

logger = logging.getLogger(__name__)


class ShipGateError(RuntimeError):
    """Raised when the ship gate rejects a release."""


@dataclass(frozen=True)
class ShipGateDecision:
    """Immutable result of a ship-gate evaluation."""

    allowed: bool
    reason: str
    pr_result: PRResult | None = None

    def __post_init__(self) -> None:
        if not self.reason.strip():
            raise ValueError("reason must be non-empty")


class ShipGate:
    """Quality gate: nothing ships until verification, authority, tests,
    and audit integrity are all satisfied and bound to the exact patch."""

    def __init__(
        self,
        publisher: GitPRPublisher,
        *,
        require_audit: bool = True,
        require_verified_state: bool = True,
    ) -> None:
        self._publisher = publisher
        self._require_audit = require_audit
        self._require_verified = require_verified_state

    # -- public API -------------------------------------------------------

    def evaluate(
        self,
        *,
        patch: PatchInfo,
        record: KnowledgeRecord,
        grant: VerifiedAuthorityGrant,
        test_results: dict[str, Any],
        audit_harness: AuditHarness | None = None,
    ) -> ShipGateDecision:
        """Evaluate every gate and return an immutable decision.

        The decision is *always* returned (never raised) so callers can
        distinguish rejection reasons.  Publication happens only when all
        gates pass inside :meth:`ship`.
        """
        try:
            self._require_verified_state(record)
            self._require_bound_grant(grant, patch)
            self._require_tests(test_results)
            if self._require_audit:
                self._verify_audit(audit_harness)
            return ShipGateDecision(allowed=True, reason="all ship gates passed")
        except ShipGateError as exc:
            return ShipGateDecision(allowed=False, reason=str(exc))

    def ship(
        self,
        *,
        patch: PatchInfo,
        pr_metadata: PRMetadata,
        record: KnowledgeRecord,
        grant: VerifiedAuthorityGrant,
        test_results: dict[str, Any],
        audit_harness: AuditHarness | None = None,
        push_remote: bool = True,
    ) -> PRResult:
        """Evaluate all gates and, when allowed, publish the PR.

        Fail closed: any rejected gate raises :class:`ShipGateError` without
        touching the publisher.
        """
        decision = self.evaluate(
            patch=patch,
            record=record,
            grant=grant,
            test_results=test_results,
            audit_harness=audit_harness,
        )
        if not decision.allowed:
            raise ShipGateError(decision.reason)

        return self._publisher.publish_patch_as_pr(
            patch=patch,
            pr_metadata=pr_metadata,
            test_results=test_results,
            authority_grant=grant,
            push_remote=push_remote,
        )

    # -- internal gates ---------------------------------------------------

    def _require_verified_state(self, record: KnowledgeRecord) -> None:
        if not self._require_verified:
            return
        if record.state is not KnowledgeState.CONFIRMED:
            raise ShipGateError(
                f"record {record.record_id} is {record.state.value}; "
                "expected CONFIRMED"
            )

    def _require_bound_grant(
        self,
        grant: VerifiedAuthorityGrant,
        patch: PatchInfo,
    ) -> None:
        if grant is None or not grant.verified:
            raise ShipGateError("authority grant failed cryptographic verification")
        parameters = dict(grant.parameters)
        if grant.action != "release.publish":
            raise ShipGateError("authority grant is not a release.publish grant")
        if parameters.get("patch_id") != patch.patch_id:
            raise ShipGateError("authority grant is not bound to this patch")
        # Resource must reference the publisher repository.
        if grant.resource != f"repository:{self._publisher.repo_full_name}":
            raise ShipGateError("authority grant is not scoped to this repository")

    def _require_tests(self, test_results: dict[str, Any]) -> None:
        if not isinstance(test_results, dict) or not test_results:
            raise ShipGateError("attested test evidence is required")
        status = str(test_results.get("status", "")).lower()
        failed = test_results.get("failed", test_results.get("failures"))
        total = test_results.get("total", test_results.get("tests_run"))
        if status not in {"pass", "passed", "success", "succeeded"}:
            raise ShipGateError("test status is not successful")
        if failed not in (0, [], None):
            raise ShipGateError("test results contain failures")
        if total is not None and (not isinstance(total, int) or total < 1):
            raise ShipGateError("test total must be a positive integer")
        if total is None and test_results.get("passed") is None:
            raise ShipGateError("test evidence must include total or passed count")

    def _verify_audit(self, audit_harness: AuditHarness | None) -> None:
        if audit_harness is None:
            raise ShipGateError("audit chain is required for release")
        try:
            audit_harness.verify()
        except ChainIntegrityError as exc:
            raise ShipGateError(f"audit chain integrity failed: {exc}") from exc


__all__ = [
    "ShipGate",
    "ShipGateDecision",
    "ShipGateError",
]
