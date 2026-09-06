"""Authoritative Delivery Contract v1 over a validated delivery candidate.

This module does not run CI, release, deployment, or arbitrary shell commands.
It deterministically evaluates one immutable DeliveryVerificationCandidate against
server-owned apply provenance, the configured trusted toolchain, and the current
trusted workspace state.
"""

from __future__ import annotations

import hashlib
import os
import stat
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path, PurePosixPath
from typing import Any, Mapping

from phase4.implementation_agent.patch_adapter import PatchExecutionRequestNotFoundError
from phase4.implementation_agent.patch_models import (
    PatchRecordStatus,
    WorkspaceFileState,
    toolchain_fingerprint,
)

from .delivery_certificate import (
    DeliveryArtifactFile,
    DeliveryVerificationCandidate,
    DeliveryVerificationStatus,
    canonical_digest,
)

DELIVERY_CONTRACT_ID = "delivery.contract.v1"
DELIVERY_CONTRACT_VERSION = "1"

_DELIVERY_CONTRACT_DEFINITION = {
    "contract_id": DELIVERY_CONTRACT_ID,
    "version": DELIVERY_CONTRACT_VERSION,
    "candidate_schema_version": 1,
    "required_candidate_status": DeliveryVerificationStatus.PENDING_AUTHORITATIVE_VERIFICATION.value,
    "required_apply_status": PatchRecordStatus.SUCCEEDED.value,
    "required_tool_kinds": ["build", "lint", "test"],
    "checks": [
        "candidate_content_identity",
        "server_registered_apply_request",
        "server_stored_apply_record",
        "committed_artifact_identity",
        "tool_evidence_identity",
        "trusted_toolchain_identity",
        "trusted_tool_executables",
        "live_workspace_file_identity",
    ],
}
DELIVERY_CONTRACT_FINGERPRINT = canonical_digest(_DELIVERY_CONTRACT_DEFINITION)


class DeliveryCertificationResult(str, Enum):
    PASS = "pass"
    FAIL = "fail"


class DeliveryCertificationUnavailableError(RuntimeError):
    """The authoritative server-side provenance required for evaluation is unavailable."""


class DeliveryCandidateContractError(ValueError):
    """A submitted candidate is not the exact canonical handoff artifact."""


@dataclass(frozen=True)
class DeliveryCertificate:
    """Immutable authoritative result for one candidate under one contract version."""

    candidate_id: str
    organization_id: str
    repository: str
    result: DeliveryCertificationResult
    reason_codes: tuple[str, ...]
    apply_record_id: str
    observed_workspace_fingerprint: str
    certified_by: str
    certified_at: datetime
    contract_id: str = DELIVERY_CONTRACT_ID
    contract_version: str = DELIVERY_CONTRACT_VERSION
    contract_fingerprint: str = DELIVERY_CONTRACT_FINGERPRINT
    certificate_id: str = field(init=False)

    def __post_init__(self) -> None:
        for name in (
            "candidate_id",
            "apply_record_id",
            "observed_workspace_fingerprint",
            "contract_fingerprint",
        ):
            value = getattr(self, name)
            if not isinstance(value, str) or len(value) != 64:
                raise ValueError(f"{name} must be a SHA-256 digest")
            if any(character not in "0123456789abcdef" for character in value):
                raise ValueError(f"{name} must be a lowercase SHA-256 digest")
        for name in (
            "organization_id",
            "repository",
            "certified_by",
            "contract_id",
            "contract_version",
        ):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip() or value != value.strip():
                raise ValueError(f"{name} must be canonical non-empty text")
        if not isinstance(self.result, DeliveryCertificationResult):
            raise TypeError("result must be a DeliveryCertificationResult")
        reasons = tuple(sorted(set(self.reason_codes)))
        if not reasons or any(not isinstance(item, str) or not item.strip() for item in reasons):
            raise ValueError("delivery certificate requires canonical reason codes")
        if self.result is DeliveryCertificationResult.PASS and reasons != ("verified",):
            raise ValueError("PASS certificate must have exactly the verified reason")
        if self.result is DeliveryCertificationResult.FAIL and "verified" in reasons:
            raise ValueError("FAIL certificate cannot contain the verified reason")
        if not isinstance(self.certified_at, datetime) or self.certified_at.tzinfo is None:
            raise ValueError("certified_at must be timezone-aware")
        object.__setattr__(self, "reason_codes", reasons)
        object.__setattr__(
            self,
            "certificate_id",
            canonical_digest(self.canonical(include_id=False)),
        )

    @property
    def authoritative(self) -> bool:
        return True

    def canonical(self, *, include_id: bool = True) -> dict[str, object]:
        payload: dict[str, object] = {
            "schema_version": 1,
            "candidate_id": self.candidate_id,
            "organization_id": self.organization_id,
            "repository": self.repository,
            "result": self.result.value,
            "authoritative": True,
            "reason_codes": list(self.reason_codes),
            "apply_record_id": self.apply_record_id,
            "observed_workspace_fingerprint": self.observed_workspace_fingerprint,
            "contract_id": self.contract_id,
            "contract_version": self.contract_version,
            "contract_fingerprint": self.contract_fingerprint,
            "certified_by": self.certified_by,
            "certified_at": self.certified_at.astimezone(timezone.utc).isoformat(),
        }
        if include_id:
            payload["certificate_id"] = self.certificate_id
        return payload


def parse_delivery_verification_candidate(
    payload: Mapping[str, Any],
) -> DeliveryVerificationCandidate:
    """Reconstruct the exact canonical handoff and reject any client-side drift."""
    if not isinstance(payload, Mapping):
        raise DeliveryCandidateContractError("candidate must be an object")
    raw = dict(payload)
    expected_keys = {
        "schema_version",
        "status",
        "authoritative",
        "verification_result",
        "organization_id",
        "repository",
        "intent_id",
        "onboarding_content_fingerprint",
        "audit_report_id",
        "audit_request_fingerprint",
        "audit_manifest_id",
        "audit_evidence_bundle_id",
        "audit_commit_sha",
        "plan_id",
        "plan_request_fingerprint",
        "proposal_id",
        "proposal_request_fingerprint",
        "apply_record_id",
        "apply_request_fingerprint",
        "artifact_id",
        "diff_sha256",
        "baseline_fingerprint",
        "toolchain_fingerprint",
        "files",
        "evidence_ids",
        "candidate_id",
    }
    if set(raw) != expected_keys:
        raise DeliveryCandidateContractError("candidate fields do not match schema version 1")
    if raw["schema_version"] != 1:
        raise DeliveryCandidateContractError("unsupported candidate schema version")
    if raw["status"] != DeliveryVerificationStatus.PENDING_AUTHORITATIVE_VERIFICATION.value:
        raise DeliveryCandidateContractError("candidate is not pending authoritative verification")
    if raw["authoritative"] is not False or raw["verification_result"] is not None:
        raise DeliveryCandidateContractError("handoff candidate cannot claim verification authority")
    raw_files = raw.get("files")
    raw_evidence_ids = raw.get("evidence_ids")
    if not isinstance(raw_files, list) or not isinstance(raw_evidence_ids, list):
        raise DeliveryCandidateContractError("candidate files/evidence are malformed")
    try:
        files = tuple(
            DeliveryArtifactFile(
                path=item["path"],
                exists=item["exists"],
                sha256=item["sha256"],
                byte_count=item["byte_count"],
                mode=item["mode"],
            )
            for item in raw_files
            if isinstance(item, Mapping)
        )
        if len(files) != len(raw_files):
            raise DeliveryCandidateContractError("candidate file manifest is malformed")
        candidate = DeliveryVerificationCandidate(
            organization_id=raw["organization_id"],
            repository=raw["repository"],
            intent_id=raw["intent_id"],
            onboarding_content_fingerprint=raw["onboarding_content_fingerprint"],
            audit_report_id=raw["audit_report_id"],
            audit_request_fingerprint=raw["audit_request_fingerprint"],
            audit_manifest_id=raw["audit_manifest_id"],
            audit_evidence_bundle_id=raw["audit_evidence_bundle_id"],
            audit_commit_sha=raw["audit_commit_sha"],
            plan_id=raw["plan_id"],
            plan_request_fingerprint=raw["plan_request_fingerprint"],
            proposal_id=raw["proposal_id"],
            proposal_request_fingerprint=raw["proposal_request_fingerprint"],
            apply_record_id=raw["apply_record_id"],
            apply_request_fingerprint=raw["apply_request_fingerprint"],
            artifact_id=raw["artifact_id"],
            diff_sha256=raw["diff_sha256"],
            baseline_fingerprint=raw["baseline_fingerprint"],
            toolchain_fingerprint=raw["toolchain_fingerprint"],
            files=files,
            evidence_ids=tuple(raw_evidence_ids),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise DeliveryCandidateContractError(str(exc)) from exc
    if raw["candidate_id"] != candidate.candidate_id or raw != candidate.canonical():
        raise DeliveryCandidateContractError("candidate_id does not match canonical candidate content")
    return candidate


class DeliveryCertificationVerifier:
    """Deterministic authoritative evaluator for Delivery Contract v1."""

    def certify(
        self,
        candidate: DeliveryVerificationCandidate,
        *,
        patch_runtime: Any,
        certified_by: str,
        certified_at: datetime | None = None,
    ) -> DeliveryCertificate:
        if not isinstance(candidate, DeliveryVerificationCandidate):
            raise TypeError("candidate must be a DeliveryVerificationCandidate")
        if not isinstance(certified_by, str) or not certified_by.strip():
            raise ValueError("certified_by must be canonical non-empty text")

        request, record = _server_apply_provenance(
            patch_runtime,
            candidate.apply_request_fingerprint,
        )
        failures: set[str] = set()

        if (
            request.request_fingerprint != candidate.apply_request_fingerprint
            or request.organization_id != candidate.organization_id
            or request.resource != candidate.repository
            or request.proposal.proposal_id != candidate.proposal_id
            or request.proposal.request_fingerprint
            != candidate.proposal_request_fingerprint
            or request.proposal.diff_sha256 != candidate.diff_sha256
            or request.baseline_fingerprint != candidate.baseline_fingerprint
            or request.toolchain_fingerprint != candidate.toolchain_fingerprint
        ):
            failures.add("apply_request_mismatch")

        artifact = record.artifact
        if (
            record.request_fingerprint != candidate.apply_request_fingerprint
            or record.proposal_id != candidate.proposal_id
            or record.baseline_fingerprint != candidate.baseline_fingerprint
            or record.record_id != candidate.apply_record_id
            or record.status is not PatchRecordStatus.SUCCEEDED
            or record.committed is not True
            or record.rolled_back is not False
            or record.error is not None
        ):
            failures.add("apply_record_mismatch")
        if (
            artifact is None
            or artifact.artifact_id != candidate.artifact_id
            or artifact.proposal_id != candidate.proposal_id
            or artifact.diff_sha256 != candidate.diff_sha256
            or artifact.baseline_fingerprint != candidate.baseline_fingerprint
            or tuple(item.canonical() for item in artifact.files)
            != tuple(item.canonical() for item in candidate.files)
        ):
            failures.add("artifact_mismatch")

        evidence_ids = tuple(sorted(item.evidence_id for item in record.evidence))
        if (
            evidence_ids != candidate.evidence_ids
            or len(record.evidence) != 3
            or any(not item.passed for item in record.evidence)
            or {item.kind.value for item in record.evidence} != {"lint", "test", "build"}
            or any(item.artifact_id != candidate.artifact_id for item in record.evidence)
        ):
            failures.add("evidence_mismatch")

        configured_tools = tuple(patch_runtime.tools)
        if toolchain_fingerprint(configured_tools) != candidate.toolchain_fingerprint:
            failures.add("toolchain_drift")
        if any(not tool.executable_matches() for tool in configured_tools):
            failures.add("tool_executable_drift")

        live_states = _observe_workspace(
            Path(patch_runtime.workspace_root),
            candidate.files,
        )
        observed_workspace_fingerprint = canonical_digest(
            [item.canonical() for item in live_states]
        )
        if tuple(item.canonical() for item in live_states) != tuple(
            item.canonical() for item in candidate.files
        ):
            failures.add("workspace_drift")

        result = (
            DeliveryCertificationResult.FAIL
            if failures
            else DeliveryCertificationResult.PASS
        )
        reasons = tuple(sorted(failures)) if failures else ("verified",)
        return DeliveryCertificate(
            candidate_id=candidate.candidate_id,
            organization_id=candidate.organization_id,
            repository=candidate.repository,
            result=result,
            reason_codes=reasons,
            apply_record_id=candidate.apply_record_id,
            observed_workspace_fingerprint=observed_workspace_fingerprint,
            certified_by=certified_by.strip(),
            certified_at=certified_at or datetime.now(timezone.utc),
        )


def _server_apply_provenance(patch_runtime: Any, request_fingerprint: str):
    """Resolve the already-registered server-owned apply request and immutable record.

    GovernedPatchExecutionRuntime currently exposes audits and workspace/tool
    configuration publicly, while the exact registered request/record is owned by
    its governed adapter. Delivery Contract v1 reads that existing canonical
    runtime state; it never trusts a client-supplied substitute.
    """
    try:
        governed_adapter = patch_runtime._governed_adapter
        requests = governed_adapter._requests
        request = requests[request_fingerprint]
        record = governed_adapter.get_record(request_fingerprint)
    except (
        AttributeError,
        KeyError,
        LookupError,
        PatchExecutionRequestNotFoundError,
    ) as exc:
        raise DeliveryCertificationUnavailableError(
            "server-owned apply provenance is unavailable for this candidate"
        ) from exc
    return request, record


def _observe_workspace(
    root: Path,
    expected_files: tuple[DeliveryArtifactFile, ...],
) -> tuple[WorkspaceFileState, ...]:
    trusted_root = root.resolve(strict=True)
    return tuple(
        _observe_one_file(trusted_root, item.path)
        for item in sorted(expected_files, key=lambda value: value.path)
    )


def _observe_one_file(root: Path, relative_path: str) -> WorkspaceFileState:
    candidate = root.joinpath(*PurePosixPath(relative_path).parts)
    resolved = candidate.resolve(strict=False)
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise DeliveryCertificationUnavailableError(
            "candidate path escapes the trusted workspace"
        ) from exc

    if not candidate.exists() and not candidate.is_symlink():
        return WorkspaceFileState(
            path=relative_path,
            exists=False,
            sha256=None,
            byte_count=0,
            mode=None,
        )
    if candidate.is_symlink():
        raise DeliveryCertificationUnavailableError(
            "candidate path is a symbolic link in the trusted workspace"
        )

    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(candidate, flags)
    except OSError as exc:
        raise DeliveryCertificationUnavailableError(
            "candidate file cannot be observed safely"
        ) from exc
    try:
        opened = os.fstat(descriptor)
        if not stat.S_ISREG(opened.st_mode):
            raise DeliveryCertificationUnavailableError(
                "candidate path is not a regular file"
            )
        digest = hashlib.sha256()
        byte_count = 0
        while chunk := os.read(descriptor, 1024 * 1024):
            digest.update(chunk)
            byte_count += len(chunk)
        after = os.fstat(descriptor)
        if (opened.st_dev, opened.st_ino, opened.st_size, opened.st_mtime_ns) != (
            after.st_dev,
            after.st_ino,
            after.st_size,
            after.st_mtime_ns,
        ):
            raise DeliveryCertificationUnavailableError(
                "candidate file changed during certification observation"
            )
        return WorkspaceFileState(
            path=relative_path,
            exists=True,
            sha256=digest.hexdigest(),
            byte_count=byte_count,
            mode=stat.S_IMODE(after.st_mode),
        )
    finally:
        os.close(descriptor)


__all__ = [
    "DELIVERY_CONTRACT_FINGERPRINT",
    "DELIVERY_CONTRACT_ID",
    "DELIVERY_CONTRACT_VERSION",
    "DeliveryCandidateContractError",
    "DeliveryCertificate",
    "DeliveryCertificationResult",
    "DeliveryCertificationUnavailableError",
    "DeliveryCertificationVerifier",
    "parse_delivery_verification_candidate",
]
