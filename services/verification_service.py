"""P3-20 independent verification gate.

The gate does not trust a specialist's PASS claim. It independently checks
identity, contract boundaries, outputs and bound evidence, then emits one
immutable PASS/FAIL result. No model calls are made here.
"""
from __future__ import annotations

from domain.verification import (
    DeliveredProduct,
    Evidence,
    VerificationCheck,
    VerificationError,
    VerificationResult,
    verification_id,
)
from domain.distribution import DispatchRecord


# Required evidence classes for release eligibility. Architecture is first-class:
# a failed or missing architecture check blocks PASS (fail-closed).
_REQUIRED_EVIDENCE = ("test", "audit", "security", "architecture", "provenance")


class VerificationService:
    """Independently verify a delivered specialist product."""

    def verify(self, dispatch: DispatchRecord, product: DeliveredProduct) -> VerificationResult:
        if not isinstance(dispatch, DispatchRecord):
            raise VerificationError("verify requires a DispatchRecord")
        if not isinstance(product, DeliveredProduct):
            raise VerificationError("verify requires a DeliveredProduct")

        checks: list[VerificationCheck] = []
        failures: list[str] = []

        def check(check_id: str, passed: bool, statement: str) -> None:
            checks.append(VerificationCheck(check_id, passed, statement))
            if not passed:
                failures.append(statement)

        check(
            "V20-DISPATCH-PACKAGE",
            bool(dispatch.package_fingerprint),
            "Dispatch is bound to a package fingerprint",
        )
        check(
            "V20-DISPATCH-CONTRACT",
            bool(dispatch.contract_fingerprint),
            "Dispatch is bound to an exact specialist contract fingerprint",
        )
        check(
            "V20-OUTPUTS-PERMITTED",
            all(output in dispatch.permitted_outputs for output in product.output_names),
            "Delivered outputs are limited to contract-permitted outputs",
        )
        check(
            "V20-OUTPUTS-NONEMPTY",
            bool(product.output_names),
            "Delivered product declares at least one output",
        )

        by_kind = {kind: [] for kind in _REQUIRED_EVIDENCE}
        for item in product.evidence:
            if item.kind in by_kind:
                by_kind[item.kind].append(item)
            self._check_evidence_binding(item, dispatch, product, check)

        for kind in _REQUIRED_EVIDENCE:
            items = by_kind[kind]
            check(
                f"V20-EVIDENCE-{kind.upper()}",
                bool(items) and all(item.passed for item in items),
                f"Required {kind} evidence is present and passed",
            )

        evidence_ids = tuple(item.evidence_id for item in product.evidence)
        status = "PASS" if not failures else "FAIL"
        result = VerificationResult(
            verification_id=verification_id(dispatch, product),
            status=status,
            package_fingerprint=dispatch.package_fingerprint,
            contract_fingerprint=dispatch.contract_fingerprint,
            dispatch_fingerprint=dispatch.fingerprint,
            artifact_fingerprint=product.artifact_fingerprint,
            checks=tuple(checks),
            evidence_ids=evidence_ids,
            failures=tuple(failures),
        )
        return result

    @staticmethod
    def _check_evidence_binding(
        evidence: Evidence,
        dispatch: DispatchRecord,
        product: DeliveredProduct,
        check,
    ) -> None:
        prefix = f"V20-EVIDENCE-BINDING-{evidence.evidence_id}"
        bound = (
            evidence.package_fingerprint == dispatch.package_fingerprint
            and evidence.contract_fingerprint == dispatch.contract_fingerprint
            and evidence.dispatch_fingerprint == dispatch.fingerprint
            and evidence.artifact_fingerprint == product.artifact_fingerprint
        )
        check(prefix, bound, f"Evidence {evidence.evidence_id} is bound to the exact dispatch and artifact")
