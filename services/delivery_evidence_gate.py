"""Bind deploy and release mutations to durable integration evidence."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import asdict
from typing import Any, Protocol

from domain.factory_integration import (
    IntegrationPlan,
    IntegrationReceipt,
    IntegrationStatus,
    ReleaseHandoff,
)
from phase4.authority.grants import VerifiedAuthorityGrant


class DeliveryEvidenceError(ValueError):
    """Delivery evidence is absent, stale, cross-tenant, or not authoritative."""


class IntegrationEvidenceStore(Protocol):
    def get_plan(
        self, organization_id: str, plan_id: str
    ) -> IntegrationPlan | None: ...

    def get_receipt_for_plan(
        self, organization_id: str, plan_fingerprint: str
    ) -> IntegrationReceipt | None: ...


class AttestedDeliveryGate:
    """Resolve the only releaseable patch from canonical durable evidence."""

    def __init__(self, store: IntegrationEvidenceStore) -> None:
        self._store = store

    def bind(
        self,
        payload: Mapping[str, Any],
        grant: VerifiedAuthorityGrant,
        *,
        action: str,
    ) -> dict[str, Any]:
        organization_id = str(payload.get("organization_id") or "")
        if not organization_id:
            raise DeliveryEvidenceError("organization_id is required")
        handoff = _handoff(payload.get("release_handoff"))
        if handoff.organization_id != organization_id:
            raise DeliveryEvidenceError("release handoff belongs to another tenant")
        receipt = self._store.get_receipt_for_plan(
            organization_id, handoff.plan_fingerprint
        )
        if receipt is None or receipt.receipt_id != handoff.integration_receipt_id:
            raise DeliveryEvidenceError("integration receipt is unavailable or changed")
        plan = self._store.get_plan(organization_id, receipt.plan_id)
        if plan is None:
            raise DeliveryEvidenceError("integration plan is unavailable")
        self._verify_handoff(handoff, receipt, plan)
        self._verify_grant(grant, handoff, action=action, payload=payload)

        bound = dict(payload)
        bound["release_handoff"] = asdict(handoff)
        bound["repository"] = plan.repository
        bound["patch_content"] = handoff.patch_content
        bound["patch_id"] = handoff.patch_fingerprint
        bound["test_results"] = _test_results(handoff.test_attestation)
        return bound

    @staticmethod
    def _verify_handoff(
        handoff: ReleaseHandoff,
        receipt: IntegrationReceipt,
        plan: IntegrationPlan,
    ) -> None:
        receipt_evidence = tuple(
            (key, value)
            for key, value in receipt.suite_attestation
            if key != "result_fingerprint"
        )
        if (
            receipt.status is not IntegrationStatus.SUCCEEDED
            or plan.status is not IntegrationStatus.SUCCEEDED
            or plan.content_fingerprint != handoff.plan_fingerprint
            or plan.repository != handoff.repository
            or plan.base_sha != handoff.base_sha
            or plan.integration_branch != handoff.branch
            or receipt.integration_head_sha != handoff.head_sha
            or receipt.integration_branch != handoff.branch
            or receipt_evidence != handoff.test_attestation
        ):
            raise DeliveryEvidenceError(
                "release handoff does not match successful integration evidence"
            )

    @staticmethod
    def _verify_grant(
        grant: VerifiedAuthorityGrant,
        handoff: ReleaseHandoff,
        *,
        action: str,
        payload: Mapping[str, Any],
    ) -> None:
        parameters = dict(grant.parameters)
        base_branch = str(payload.get("base_branch") or "main")
        expected = {
            "integration_receipt_id": handoff.integration_receipt_id,
            "plan_fingerprint": handoff.plan_fingerprint,
            "base_sha": handoff.base_sha,
            "head_sha": handoff.head_sha,
            "patch_fingerprint": handoff.patch_fingerprint,
        }
        if action == "release.publish":
            expected["base_branch"] = base_branch
            expected["patch_id"] = handoff.patch_fingerprint
        if (
            not grant.verified
            or grant.action != action
            or grant.capability != action
            or grant.organization_id != handoff.organization_id
            or grant.resource != f"repository:{handoff.repository}"
            or any(parameters.get(key) != value for key, value in expected.items())
        ):
            raise DeliveryEvidenceError(
                "authority grant is not bound to attested delivery evidence"
            )


def _handoff(value: Any) -> ReleaseHandoff:
    if isinstance(value, ReleaseHandoff):
        return value
    if not isinstance(value, Mapping):
        raise DeliveryEvidenceError("release_handoff is required")
    try:
        return ReleaseHandoff(
            organization_id=str(value["organization_id"]),
            integration_receipt_id=str(value["integration_receipt_id"]),
            plan_fingerprint=str(value["plan_fingerprint"]),
            repository=str(value["repository"]),
            base_sha=str(value["base_sha"]),
            head_sha=str(value["head_sha"]),
            branch=str(value["branch"]),
            patch_content=str(value["patch_content"]),
            patch_fingerprint=str(value["patch_fingerprint"]),
            test_attestation=tuple(
                (str(key), str(item)) for key, item in value["test_attestation"]
            ),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise DeliveryEvidenceError("release_handoff is malformed") from exc


def _test_results(attestation: tuple[tuple[str, str], ...]) -> dict[str, Any]:
    result: dict[str, Any] = dict(attestation)
    for name in ("tests_run", "total", "passed", "failed", "failures"):
        value = result.get(name)
        if isinstance(value, str) and value.isdigit():
            result[name] = int(value)
    return result
