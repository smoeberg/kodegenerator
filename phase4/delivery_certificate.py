"""Immutable non-authoritative handoff from governed apply to delivery verification."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from enum import Enum
from pathlib import PurePosixPath

_HEX64 = re.compile(r"^[0-9a-f]{64}$")


class DeliveryVerificationStatus(str, Enum):
    PENDING_AUTHORITATIVE_VERIFICATION = "pending_authoritative_verification"


@dataclass(frozen=True, order=True)
class DeliveryArtifactFile:
    path: str
    exists: bool
    sha256: str | None
    byte_count: int
    mode: int | None

    def __post_init__(self) -> None:
        if not isinstance(self.path, str) or not self.path or self.path != self.path.strip():
            raise ValueError("delivery artifact path must be canonical and non-empty")
        candidate = PurePosixPath(self.path)
        if candidate.is_absolute() or candidate.as_posix() != self.path:
            raise ValueError("delivery artifact path must be repository-relative POSIX")
        if any(part in {"", ".", ".."} for part in candidate.parts):
            raise ValueError("delivery artifact path cannot contain traversal segments")
        if type(self.exists) is not bool:
            raise TypeError("delivery artifact exists must be boolean")
        if type(self.byte_count) is not int or self.byte_count < 0:
            raise ValueError("delivery artifact byte_count must be non-negative")
        if self.exists:
            _require_digest(self.sha256, "delivery artifact sha256")
            if type(self.mode) is not int or self.mode < 0:
                raise ValueError("existing delivery artifact files require a mode")
        elif self.sha256 is not None or self.byte_count != 0 or self.mode is not None:
            raise ValueError("absent delivery artifact files cannot carry content metadata")

    def canonical(self) -> dict[str, object]:
        return {
            "path": self.path,
            "exists": self.exists,
            "sha256": self.sha256,
            "byte_count": self.byte_count,
            "mode": self.mode,
        }


@dataclass(frozen=True)
class DeliveryVerificationCandidate:
    """Content-addressed proof that one governed apply is ready for a real gate."""

    organization_id: str
    repository: str
    intent_id: str
    onboarding_content_fingerprint: str
    audit_report_id: str
    audit_request_fingerprint: str
    audit_manifest_id: str
    audit_evidence_bundle_id: str
    audit_commit_sha: str
    plan_id: str
    plan_request_fingerprint: str
    proposal_id: str
    proposal_request_fingerprint: str
    apply_record_id: str
    apply_request_fingerprint: str
    artifact_id: str
    diff_sha256: str
    baseline_fingerprint: str
    toolchain_fingerprint: str
    files: tuple[DeliveryArtifactFile, ...]
    evidence_ids: tuple[str, ...]
    project_id: str | None = None
    status: DeliveryVerificationStatus = DeliveryVerificationStatus.PENDING_AUTHORITATIVE_VERIFICATION
    candidate_id: str = field(init=False)

    def __post_init__(self) -> None:
        for name in (
            "organization_id",
            "repository",
            "intent_id",
            "audit_report_id",
            "audit_commit_sha",
            "plan_id",
        ):
            _require_text(getattr(self, name), name)
        if self.project_id is not None:
            _require_text(self.project_id, "project_id")
        for name in (
            "onboarding_content_fingerprint",
            "audit_request_fingerprint",
            "audit_manifest_id",
            "audit_evidence_bundle_id",
            "plan_request_fingerprint",
            "proposal_id",
            "proposal_request_fingerprint",
            "apply_record_id",
            "apply_request_fingerprint",
            "artifact_id",
            "diff_sha256",
            "baseline_fingerprint",
            "toolchain_fingerprint",
        ):
            _require_digest(getattr(self, name), name)
        if not isinstance(self.status, DeliveryVerificationStatus):
            raise TypeError("status must be a DeliveryVerificationStatus")
        files = tuple(sorted(self.files, key=lambda item: item.path))
        if not files or any(not isinstance(item, DeliveryArtifactFile) for item in files):
            raise ValueError("delivery candidate requires committed artifact files")
        if len(files) != len({item.path for item in files}):
            raise ValueError("delivery candidate artifact paths must be unique")
        evidence_ids = tuple(sorted(self.evidence_ids))
        if len(evidence_ids) != 3 or len(evidence_ids) != len(set(evidence_ids)):
            raise ValueError("delivery candidate requires exactly three unique tool evidence IDs")
        for evidence_id in evidence_ids:
            _require_digest(evidence_id, "evidence_id")
        object.__setattr__(self, "files", files)
        object.__setattr__(self, "evidence_ids", evidence_ids)
        object.__setattr__(self, "candidate_id", canonical_digest(self.canonical(include_id=False)))

    @property
    def authoritative(self) -> bool:
        return False

    @property
    def verification_result(self) -> None:
        return None

    def canonical(self, *, include_id: bool = True) -> dict[str, object]:
        payload: dict[str, object] = {
            "schema_version": 2 if self.project_id is not None else 1,
            "status": self.status.value,
            "authoritative": False,
            "verification_result": None,
            "organization_id": self.organization_id,
            "repository": self.repository,
            "intent_id": self.intent_id,
            "onboarding_content_fingerprint": self.onboarding_content_fingerprint,
            "audit_report_id": self.audit_report_id,
            "audit_request_fingerprint": self.audit_request_fingerprint,
            "audit_manifest_id": self.audit_manifest_id,
            "audit_evidence_bundle_id": self.audit_evidence_bundle_id,
            "audit_commit_sha": self.audit_commit_sha,
            "plan_id": self.plan_id,
            "plan_request_fingerprint": self.plan_request_fingerprint,
            "proposal_id": self.proposal_id,
            "proposal_request_fingerprint": self.proposal_request_fingerprint,
            "apply_record_id": self.apply_record_id,
            "apply_request_fingerprint": self.apply_request_fingerprint,
            "artifact_id": self.artifact_id,
            "diff_sha256": self.diff_sha256,
            "baseline_fingerprint": self.baseline_fingerprint,
            "toolchain_fingerprint": self.toolchain_fingerprint,
            "files": [item.canonical() for item in self.files],
            "evidence_ids": list(self.evidence_ids),
        }
        if self.project_id is not None:
            payload["project_id"] = self.project_id
        if include_id:
            payload["candidate_id"] = self.candidate_id
        return payload


def canonical_digest(value: object) -> str:
    encoded = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _require_text(value: object, name: str) -> str:
    if not isinstance(value, str) or not value or value != value.strip():
        raise ValueError(f"{name} must be canonical non-empty text")
    return value


def _require_digest(value: object, name: str) -> str:
    if not isinstance(value, str) or not _HEX64.fullmatch(value):
        raise ValueError(f"{name} must be a lowercase SHA-256 digest")
    return value


__all__ = [
    "DeliveryArtifactFile",
    "DeliveryVerificationCandidate",
    "DeliveryVerificationStatus",
    "canonical_digest",
]
