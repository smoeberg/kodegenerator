"""Human-authoritative multi-spec acceptance over verified artifact traceability.

Acceptance v1 combines multiple COMPLETE requirement traceability manifests that
all resolve to the same PASS-certified artifact file set. The backend verifies
bundle/reference integrity; the authenticated organization admin owns the human
acceptance attestation. This contract does not machine-prove semantic requirement
satisfaction and grants no release, deploy, merge, or execution authority.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
import re
from typing import Any, Mapping, Sequence

from phase4.delivery_certificate import DeliveryVerificationCandidate, canonical_digest
from phase4.delivery_certification import DeliveryCertificate, DeliveryCertificationResult
from phase4.requirements_traceability import (
    RequirementTraceabilityError,
    RequirementTraceabilityManifest,
    TraceCoverageStatus,
)


ARTIFACT_ACCEPTANCE_SCHEMA_VERSION = 1
ARTIFACT_ACCEPTANCE_CONTRACT_ID = "artifact.acceptance.multi_spec.v1"
ARTIFACT_ACCEPTANCE_CONTRACT_VERSION = "1"
_MIN_SPECS = 2
_MAX_SPECS = 16
_MAX_RATIONALE_CHARS = 2_000
_HEX64 = re.compile(r"^[0-9a-f]{64}$")

_ARTIFACT_ACCEPTANCE_CONTRACT = {
    "contract_id": ARTIFACT_ACCEPTANCE_CONTRACT_ID,
    "version": ARTIFACT_ACCEPTANCE_CONTRACT_VERSION,
    "minimum_distinct_specs": _MIN_SPECS,
    "maximum_specs": _MAX_SPECS,
    "required_traceability_status": TraceCoverageStatus.COMPLETE.value,
    "required_delivery_result": DeliveryCertificationResult.PASS.value,
    "same_repository": True,
    "same_artifact_file_set": True,
    "distinct_plan_request_fingerprints": True,
    "human_admin_attestation_required": True,
    "machine_semantic_verification": False,
    "release_authority": False,
}
ARTIFACT_ACCEPTANCE_CONTRACT_FINGERPRINT = canonical_digest(
    _ARTIFACT_ACCEPTANCE_CONTRACT
)


class ArtifactAcceptanceError(ValueError):
    """The submitted manifests cannot form one exact verified acceptance bundle."""


class ArtifactAcceptanceStatus(str, Enum):
    ACCEPTED = "accepted"


@dataclass(frozen=True, order=True)
class AcceptedSpecBinding:
    """One immutable spec/traceability binding included in an acceptance bundle."""

    manifest_id: str
    certificate_id: str
    candidate_id: str
    plan_id: str
    plan_request_fingerprint: str
    requirement_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        for name in (
            "manifest_id",
            "certificate_id",
            "candidate_id",
            "plan_request_fingerprint",
        ):
            _require_digest(getattr(self, name), name)
        _require_text(self.plan_id, "plan_id")
        requirement_ids = tuple(sorted(self.requirement_ids))
        if not requirement_ids or len(requirement_ids) != len(set(requirement_ids)):
            raise ArtifactAcceptanceError(
                "accepted spec binding requires unique requirement IDs"
            )
        for requirement_id in requirement_ids:
            _require_digest(requirement_id, "requirement_id")
        object.__setattr__(self, "requirement_ids", requirement_ids)

    def canonical(self) -> dict[str, object]:
        return {
            "manifest_id": self.manifest_id,
            "certificate_id": self.certificate_id,
            "candidate_id": self.candidate_id,
            "plan_id": self.plan_id,
            "plan_request_fingerprint": self.plan_request_fingerprint,
            "requirement_ids": list(self.requirement_ids),
        }


@dataclass(frozen=True)
class MultiSpecArtifactAcceptance:
    """Immutable human-authoritative acceptance of one verified artifact file set."""

    organization_id: str
    repository: str
    artifact_set_fingerprint: str
    bundle_fingerprint: str
    specs: tuple[AcceptedSpecBinding, ...]
    accepted_by: str
    accepted_at: datetime
    rationale: str = ""
    contract_id: str = ARTIFACT_ACCEPTANCE_CONTRACT_ID
    contract_version: str = ARTIFACT_ACCEPTANCE_CONTRACT_VERSION
    contract_fingerprint: str = ARTIFACT_ACCEPTANCE_CONTRACT_FINGERPRINT
    acceptance_id: str = field(init=False)

    def __post_init__(self) -> None:
        for name in ("organization_id", "repository", "accepted_by"):
            _require_text(getattr(self, name), name)
        for name in (
            "artifact_set_fingerprint",
            "bundle_fingerprint",
            "contract_fingerprint",
        ):
            _require_digest(getattr(self, name), name)
        if self.contract_id != ARTIFACT_ACCEPTANCE_CONTRACT_ID:
            raise ArtifactAcceptanceError("unsupported artifact acceptance contract")
        if self.contract_version != ARTIFACT_ACCEPTANCE_CONTRACT_VERSION:
            raise ArtifactAcceptanceError("unsupported artifact acceptance contract version")
        if self.contract_fingerprint != ARTIFACT_ACCEPTANCE_CONTRACT_FINGERPRINT:
            raise ArtifactAcceptanceError("artifact acceptance contract fingerprint drifted")
        if not isinstance(self.accepted_at, datetime) or self.accepted_at.tzinfo is None:
            raise ArtifactAcceptanceError("accepted_at must be timezone-aware")
        if not isinstance(self.rationale, str) or self.rationale != self.rationale.strip():
            raise ArtifactAcceptanceError(
                "acceptance rationale must be canonical text without outer whitespace"
            )
        if len(self.rationale) > _MAX_RATIONALE_CHARS:
            raise ArtifactAcceptanceError(
                f"acceptance rationale exceeds {_MAX_RATIONALE_CHARS} characters"
            )
        specs = tuple(sorted(self.specs, key=lambda item: item.manifest_id))
        if not _MIN_SPECS <= len(specs) <= _MAX_SPECS:
            raise ArtifactAcceptanceError(
                f"multi-spec acceptance requires {_MIN_SPECS}..{_MAX_SPECS} specs"
            )
        if len({item.manifest_id for item in specs}) != len(specs):
            raise ArtifactAcceptanceError("manifest IDs must be unique")
        if len({item.plan_request_fingerprint for item in specs}) < _MIN_SPECS:
            raise ArtifactAcceptanceError(
                "multi-spec acceptance requires at least two distinct plan fingerprints"
            )
        expected_bundle = artifact_acceptance_bundle_fingerprint(
            artifact_set_fingerprint=self.artifact_set_fingerprint,
            manifest_ids=tuple(item.manifest_id for item in specs),
        )
        if self.bundle_fingerprint != expected_bundle:
            raise ArtifactAcceptanceError("acceptance bundle fingerprint drifted")
        object.__setattr__(self, "specs", specs)
        object.__setattr__(
            self,
            "acceptance_id",
            canonical_digest(self.canonical(include_id=False)),
        )

    @property
    def status(self) -> ArtifactAcceptanceStatus:
        return ArtifactAcceptanceStatus.ACCEPTED

    @property
    def authoritative(self) -> bool:
        return True

    @property
    def release_authority(self) -> bool:
        return False

    def canonical(self, *, include_id: bool = True) -> dict[str, object]:
        requirement_ids = {
            requirement_id
            for spec in self.specs
            for requirement_id in spec.requirement_ids
        }
        payload: dict[str, object] = {
            "schema_version": ARTIFACT_ACCEPTANCE_SCHEMA_VERSION,
            "status": self.status.value,
            "authoritative": True,
            "authority_scope": "multi_spec_artifact_acceptance",
            "organization_id": self.organization_id,
            "repository": self.repository,
            "artifact_set_fingerprint": self.artifact_set_fingerprint,
            "bundle_fingerprint": self.bundle_fingerprint,
            "contract_id": self.contract_id,
            "contract_version": self.contract_version,
            "contract_fingerprint": self.contract_fingerprint,
            "specs": [item.canonical() for item in self.specs],
            "summary": {
                "spec_count": len(self.specs),
                "distinct_requirement_count": len(requirement_ids),
            },
            "human_attested": True,
            "machine_semantic_verification": None,
            "release_authority": False,
            "deploy_authority": False,
            "merge_authority": False,
            "execution_authority": False,
            "accepted_by": self.accepted_by,
            "accepted_at": self.accepted_at.astimezone(timezone.utc).isoformat(),
            "rationale": self.rationale,
        }
        if include_id:
            payload["acceptance_id"] = self.acceptance_id
        return payload


def artifact_file_set_fingerprint(candidate: DeliveryVerificationCandidate) -> str:
    """Content-address only the exact committed file states, independent of proposal path."""
    if not isinstance(candidate, DeliveryVerificationCandidate):
        raise TypeError("candidate must be a DeliveryVerificationCandidate")
    files = [item.canonical() for item in sorted(candidate.files, key=lambda value: value.path)]
    if not files:
        raise ArtifactAcceptanceError("delivery candidate contains no artifact files")
    return canonical_digest(
        {
            "schema_version": 1,
            "repository": candidate.repository,
            "files": files,
        }
    )


def artifact_acceptance_bundle_fingerprint(
    *, artifact_set_fingerprint: str, manifest_ids: Sequence[str]
) -> str:
    _require_digest(artifact_set_fingerprint, "artifact_set_fingerprint")
    ids = tuple(sorted(manifest_ids))
    if not _MIN_SPECS <= len(ids) <= _MAX_SPECS:
        raise ArtifactAcceptanceError(
            f"acceptance bundle requires {_MIN_SPECS}..{_MAX_SPECS} manifests"
        )
    if len(ids) != len(set(ids)):
        raise ArtifactAcceptanceError("manifest IDs must be unique")
    for manifest_id in ids:
        _require_digest(manifest_id, "manifest_id")
    return canonical_digest(
        {
            "schema_version": 1,
            "contract_fingerprint": ARTIFACT_ACCEPTANCE_CONTRACT_FINGERPRINT,
            "artifact_set_fingerprint": artifact_set_fingerprint,
            "manifest_ids": list(ids),
        }
    )


def build_multi_spec_artifact_acceptance(
    *,
    manifests: Sequence[RequirementTraceabilityManifest],
    certificates: Sequence[DeliveryCertificate],
    candidates: Sequence[DeliveryVerificationCandidate],
    accepted_by: str,
    rationale: str = "",
    accepted_at: datetime | None = None,
) -> MultiSpecArtifactAcceptance:
    """Verify one exact multi-spec bundle and create the human acceptance record."""
    if not (len(manifests) == len(certificates) == len(candidates)):
        raise ArtifactAcceptanceError(
            "manifests, certificates and candidates must have the same length"
        )
    if not _MIN_SPECS <= len(manifests) <= _MAX_SPECS:
        raise ArtifactAcceptanceError(
            f"multi-spec acceptance requires {_MIN_SPECS}..{_MAX_SPECS} manifests"
        )
    _require_text(accepted_by, "accepted_by")

    bindings: list[AcceptedSpecBinding] = []
    organization_id: str | None = None
    repository: str | None = None
    artifact_fingerprint: str | None = None

    for manifest, certificate, candidate in zip(
        manifests, certificates, candidates, strict=True
    ):
        if not isinstance(manifest, RequirementTraceabilityManifest):
            raise TypeError("manifests must contain RequirementTraceabilityManifest values")
        if not isinstance(certificate, DeliveryCertificate):
            raise TypeError("certificates must contain DeliveryCertificate values")
        if not isinstance(candidate, DeliveryVerificationCandidate):
            raise TypeError("candidates must contain DeliveryVerificationCandidate values")
        if manifest.status is not TraceCoverageStatus.COMPLETE:
            raise ArtifactAcceptanceError(
                "artifact acceptance requires COMPLETE traceability manifests"
            )
        if certificate.result is not DeliveryCertificationResult.PASS:
            raise ArtifactAcceptanceError(
                "artifact acceptance requires PASS delivery certificates"
            )
        if manifest.certificate_id != certificate.certificate_id:
            raise ArtifactAcceptanceError("traceability manifest/certificate binding drifted")
        if (
            manifest.candidate_id != candidate.candidate_id
            or certificate.candidate_id != candidate.candidate_id
        ):
            raise ArtifactAcceptanceError("candidate binding drifted across acceptance inputs")
        if (
            manifest.plan_id != candidate.plan_id
            or manifest.plan_request_fingerprint != candidate.plan_request_fingerprint
        ):
            raise ArtifactAcceptanceError("traceability manifest/plan binding drifted")
        if not (
            manifest.organization_id
            == certificate.organization_id
            == candidate.organization_id
        ):
            raise ArtifactAcceptanceError("tenant binding drifted across acceptance inputs")
        if not manifest.repository == certificate.repository == candidate.repository:
            raise ArtifactAcceptanceError("repository binding drifted across acceptance inputs")

        current_artifact_fingerprint = artifact_file_set_fingerprint(candidate)
        if organization_id is None:
            organization_id = manifest.organization_id
            repository = manifest.repository
            artifact_fingerprint = current_artifact_fingerprint
        elif (
            manifest.organization_id != organization_id
            or manifest.repository != repository
            or current_artifact_fingerprint != artifact_fingerprint
        ):
            raise ArtifactAcceptanceError(
                "all specs must resolve to the same tenant, repository and artifact file set"
            )

        bindings.append(
            AcceptedSpecBinding(
                manifest_id=manifest.manifest_id,
                certificate_id=certificate.certificate_id,
                candidate_id=candidate.candidate_id,
                plan_id=manifest.plan_id,
                plan_request_fingerprint=manifest.plan_request_fingerprint,
                requirement_ids=tuple(item.requirement_id for item in manifest.requirements),
            )
        )

    assert organization_id is not None and repository is not None and artifact_fingerprint is not None
    manifest_ids = tuple(item.manifest_id for item in bindings)
    bundle_fingerprint = artifact_acceptance_bundle_fingerprint(
        artifact_set_fingerprint=artifact_fingerprint,
        manifest_ids=manifest_ids,
    )
    return MultiSpecArtifactAcceptance(
        organization_id=organization_id,
        repository=repository,
        artifact_set_fingerprint=artifact_fingerprint,
        bundle_fingerprint=bundle_fingerprint,
        specs=tuple(bindings),
        accepted_by=accepted_by.strip(),
        accepted_at=accepted_at or datetime.now(timezone.utc),
        rationale=rationale,
    )


def parse_multi_spec_artifact_acceptance(
    payload: Mapping[str, Any],
) -> MultiSpecArtifactAcceptance:
    """Reconstruct and content-verify one serialized acceptance record."""
    if not isinstance(payload, Mapping):
        raise ArtifactAcceptanceError("artifact acceptance payload must be an object")
    raw = dict(payload)
    if raw.get("schema_version") != ARTIFACT_ACCEPTANCE_SCHEMA_VERSION:
        raise ArtifactAcceptanceError("unsupported artifact acceptance schema")
    if raw.get("status") != ArtifactAcceptanceStatus.ACCEPTED.value:
        raise ArtifactAcceptanceError("artifact acceptance status is invalid")
    if raw.get("authoritative") is not True or raw.get("human_attested") is not True:
        raise ArtifactAcceptanceError("artifact acceptance authority/attestation is invalid")
    if raw.get("authority_scope") != "multi_spec_artifact_acceptance":
        raise ArtifactAcceptanceError("artifact acceptance authority scope drifted")
    if raw.get("machine_semantic_verification") is not None:
        raise ArtifactAcceptanceError("v1 cannot claim machine semantic verification")
    for key in (
        "release_authority",
        "deploy_authority",
        "merge_authority",
        "execution_authority",
    ):
        if raw.get(key) is not False:
            raise ArtifactAcceptanceError(f"{key} must remain false")
    raw_specs = raw.get("specs")
    if not isinstance(raw_specs, list):
        raise ArtifactAcceptanceError("acceptance specs are malformed")
    try:
        specs = tuple(
            AcceptedSpecBinding(
                manifest_id=str(item["manifest_id"]),
                certificate_id=str(item["certificate_id"]),
                candidate_id=str(item["candidate_id"]),
                plan_id=str(item["plan_id"]),
                plan_request_fingerprint=str(item["plan_request_fingerprint"]),
                requirement_ids=tuple(item["requirement_ids"]),
            )
            for item in raw_specs
            if isinstance(item, Mapping)
        )
        if len(specs) != len(raw_specs):
            raise ArtifactAcceptanceError("acceptance spec binding is malformed")
        acceptance = MultiSpecArtifactAcceptance(
            organization_id=str(raw["organization_id"]),
            repository=str(raw["repository"]),
            artifact_set_fingerprint=str(raw["artifact_set_fingerprint"]),
            bundle_fingerprint=str(raw["bundle_fingerprint"]),
            specs=specs,
            accepted_by=str(raw["accepted_by"]),
            accepted_at=datetime.fromisoformat(str(raw["accepted_at"])),
            rationale=str(raw.get("rationale") or ""),
            contract_id=str(raw["contract_id"]),
            contract_version=str(raw["contract_version"]),
            contract_fingerprint=str(raw["contract_fingerprint"]),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise ArtifactAcceptanceError(str(exc)) from exc
    if acceptance.canonical() != raw:
        raise ArtifactAcceptanceError(
            "acceptance_id/content does not match canonical acceptance payload"
        )
    return acceptance


def artifact_acceptance_request_fingerprint(
    acceptance: MultiSpecArtifactAcceptance,
) -> str:
    """Bind command replay to exact intent while excluding server creation time/ID."""
    payload = acceptance.canonical(include_id=False)
    payload.pop("accepted_at", None)
    return canonical_digest(payload)


def _require_digest(value: object, name: str) -> str:
    if not isinstance(value, str) or _HEX64.fullmatch(value) is None:
        raise ArtifactAcceptanceError(f"{name} must be a lowercase SHA-256 digest")
    return value


def _require_text(value: object, name: str) -> str:
    if not isinstance(value, str) or not value.strip() or value != value.strip():
        raise ArtifactAcceptanceError(f"{name} must be canonical non-empty text")
    return value


__all__ = [
    "ARTIFACT_ACCEPTANCE_CONTRACT_FINGERPRINT",
    "ARTIFACT_ACCEPTANCE_CONTRACT_ID",
    "ARTIFACT_ACCEPTANCE_CONTRACT_VERSION",
    "AcceptedSpecBinding",
    "ArtifactAcceptanceError",
    "ArtifactAcceptanceStatus",
    "MultiSpecArtifactAcceptance",
    "artifact_acceptance_bundle_fingerprint",
    "artifact_acceptance_request_fingerprint",
    "artifact_file_set_fingerprint",
    "build_multi_spec_artifact_acceptance",
    "parse_multi_spec_artifact_acceptance",
]
