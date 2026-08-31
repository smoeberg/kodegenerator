"""Immutable contracts for governed candidate integration and release handoff."""

from __future__ import annotations

import re
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from enum import Enum

from domain.factory_work import fingerprint

_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_SHA1 = re.compile(r"^[a-f0-9]{40}$")
_SHA256 = re.compile(r"^[a-f0-9]{64}$")


def _now() -> datetime:
    return datetime.now(timezone.utc)


class IntegrationStatus(str, Enum):
    READY = "ready"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    CONFLICT = "conflict"
    FAILED = "failed"


@dataclass(frozen=True)
class IntegrationCandidate:
    candidate_id: str
    selection_id: str
    work_package_fingerprint: str
    head_sha: str
    commit_shas: tuple[str, ...]

    def __post_init__(self) -> None:
        if not _ID.fullmatch(self.candidate_id):
            raise ValueError("candidate_id must be canonical")
        if not _SHA256.fullmatch(self.selection_id):
            raise ValueError("selection_id must be SHA-256")
        if not _SHA256.fullmatch(self.work_package_fingerprint):
            raise ValueError("work package fingerprint must be SHA-256")
        if not _SHA1.fullmatch(self.head_sha) or not self.commit_shas:
            raise ValueError("candidate requires an exact head and commits")
        if any(not _SHA1.fullmatch(value) for value in self.commit_shas):
            raise ValueError("candidate commits must be exact Git SHA-1 values")
        if self.commit_shas[-1] != self.head_sha:
            raise ValueError("candidate head must equal its final ordered commit")


@dataclass(frozen=True)
class IntegrationPlan:
    organization_id: str
    plan_id: str
    workflow_id: str
    repository: str
    base_sha: str
    candidates: tuple[IntegrationCandidate, ...]
    dependency_evidence: tuple[str, ...]
    compatibility_evidence: tuple[str, ...]
    integration_branch: str
    required_checks: tuple[str, ...]
    idempotency_key: str
    authority_action: str = "factory.integrate"
    status: IntegrationStatus = IntegrationStatus.READY
    version: int = 0
    created_at: datetime = field(default_factory=_now)

    def __post_init__(self) -> None:
        for name in ("organization_id", "plan_id", "workflow_id"):
            if not _ID.fullmatch(getattr(self, name)):
                raise ValueError(f"{name} must be canonical")
        if not self.repository.strip() or not _SHA1.fullmatch(self.base_sha):
            raise ValueError("repository and exact base SHA are required")
        if not self.candidates or len({c.candidate_id for c in self.candidates}) != len(
            self.candidates
        ):
            raise ValueError("ordered candidates must be non-empty and unique")
        for values in (
            self.dependency_evidence,
            self.compatibility_evidence,
            self.required_checks,
        ):
            if not values or values != tuple(sorted(set(values))):
                raise ValueError("integration evidence must be sorted and unique")
        if not re.fullmatch(
            r"factory/integration/[a-z0-9._-]+", self.integration_branch
        ):
            raise ValueError("integration branch is not canonical")
        if self.authority_action != "factory.integrate":
            raise ValueError("integration requires factory.integrate authority")
        if not self.idempotency_key.strip() or self.version < 0:
            raise ValueError("idempotency key and version are required")

    @property
    def content_fingerprint(self) -> str:
        return fingerprint(
            {
                "organization_id": self.organization_id,
                "plan_id": self.plan_id,
                "workflow_id": self.workflow_id,
                "repository": self.repository,
                "base_sha": self.base_sha,
                "candidates": [candidate.__dict__ for candidate in self.candidates],
                "dependency_evidence": self.dependency_evidence,
                "compatibility_evidence": self.compatibility_evidence,
                "integration_branch": self.integration_branch,
                "required_checks": self.required_checks,
                "idempotency_key": self.idempotency_key,
                "authority_action": self.authority_action,
            }
        )

    def transition(self, target: IntegrationStatus) -> IntegrationPlan:
        allowed = {
            IntegrationStatus.READY: {IntegrationStatus.RUNNING},
            IntegrationStatus.RUNNING: {
                IntegrationStatus.SUCCEEDED,
                IntegrationStatus.CONFLICT,
                IntegrationStatus.FAILED,
            },
            IntegrationStatus.SUCCEEDED: set(),
            IntegrationStatus.CONFLICT: set(),
            IntegrationStatus.FAILED: set(),
        }
        if target not in allowed[self.status]:
            raise ValueError(
                f"invalid integration transition: {self.status} -> {target}"
            )
        return replace(self, status=target, version=self.version + 1)


@dataclass(frozen=True)
class IntegrationReceipt:
    organization_id: str
    receipt_id: str
    plan_id: str
    plan_fingerprint: str
    side_effect_idempotency_key: str
    side_effect_request_fingerprint: str
    integration_branch: str
    integration_head_sha: str
    integrated_candidate_ids: tuple[str, ...]
    conflict_paths: tuple[str, ...]
    suite_attestation: tuple[tuple[str, str], ...]
    status: IntegrationStatus
    completed_at: datetime = field(default_factory=_now)

    def __post_init__(self) -> None:
        for name in ("organization_id", "plan_id"):
            if not _ID.fullmatch(getattr(self, name)):
                raise ValueError(f"{name} must be canonical")
        for name in (
            "receipt_id",
            "plan_fingerprint",
            "side_effect_request_fingerprint",
        ):
            if not _SHA256.fullmatch(getattr(self, name)):
                raise ValueError(f"{name} must be SHA-256")
        if not _SHA1.fullmatch(self.integration_head_sha):
            raise ValueError("integration head must be exact")
        if self.status not in {
            IntegrationStatus.SUCCEEDED,
            IntegrationStatus.CONFLICT,
            IntegrationStatus.FAILED,
        }:
            raise ValueError("receipt must be terminal")
        if (
            self.status is IntegrationStatus.SUCCEEDED
            and dict(self.suite_attestation).get("status") != "passed"
        ):
            raise ValueError("successful integration requires passing suite evidence")

    @property
    def content_fingerprint(self) -> str:
        return fingerprint(
            {
                key: value.value if isinstance(value, Enum) else value
                for key, value in self.__dict__.items()
                if key not in {"receipt_id", "completed_at"}
            }
        )


@dataclass(frozen=True)
class ReleaseHandoff:
    organization_id: str
    integration_receipt_id: str
    plan_fingerprint: str
    repository: str
    base_sha: str
    head_sha: str
    branch: str
    patch_content: str
    patch_fingerprint: str
    test_attestation: tuple[tuple[str, str], ...]

    def __post_init__(self) -> None:
        if dict(self.test_attestation).get("status") != "passed":
            raise ValueError("release handoff requires passing integration evidence")
        for value in (self.plan_fingerprint, self.patch_fingerprint):
            if not _SHA256.fullmatch(value):
                raise ValueError("handoff fingerprints must be SHA-256")
        if not _SHA1.fullmatch(self.base_sha) or not _SHA1.fullmatch(self.head_sha):
            raise ValueError("handoff must bind exact Git commits")
        if fingerprint(self.patch_content) != self.patch_fingerprint:
            raise ValueError("handoff patch content does not match its fingerprint")
