"""Immutable requirement-to-artifact traceability over a PASS delivery certificate.

Traceability is not semantic verification. This contract proves that the declared
planning requirements are the exact requirements bound into the AI-6 request and
that every referenced artifact path/evidence ID belongs to the certified delivery
candidate. It never claims that a requirement is semantically satisfied and grants
no release, deploy, merge, or execution authority.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import PurePosixPath
import re
from typing import Any, Mapping

from phase4.delivery_certificate import (
    DeliveryVerificationCandidate,
    canonical_digest,
)
from phase4.delivery_certification import (
    DeliveryCertificate,
    DeliveryCertificationResult,
)


TRACEABILITY_SCHEMA_VERSION = 1
_MAX_REQUIREMENT_CHARS = 4_000
_MAX_RATIONALE_CHARS = 2_000
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_PLANNING_PROVENANCE_KEYS = frozenset(
    {
        "intent_id",
        "content_fingerprint",
        "report_id",
        "audit_request_fingerprint",
        "manifest_id",
        "evidence_bundle_id",
        "commit_sha",
        "repository",
        "purpose",
        "recommendation",
    }
)


class RequirementTraceabilityError(ValueError):
    """Traceability cannot establish exact requirement/certificate provenance."""


class RequirementKind(str, Enum):
    OBJECTIVE = "objective"
    ACCEPTANCE_CRITERIA = "acceptance_criteria"
    CONSTRAINTS = "constraints"


class TraceCoverageStatus(str, Enum):
    COMPLETE = "complete"
    PARTIAL = "partial"


@dataclass(frozen=True)
class PlanningRequirements:
    """Canonical human planning declaration already bound by AI-6 fingerprinting."""

    objective: str
    acceptance_criteria: str
    constraints: str = ""

    def __post_init__(self) -> None:
        for name in ("objective", "acceptance_criteria"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value or value != value.strip():
                raise RequirementTraceabilityError(
                    f"{name} must be canonical non-empty text"
                )
        if not isinstance(self.constraints, str) or self.constraints != self.constraints.strip():
            raise RequirementTraceabilityError(
                "constraints must be canonical text without outer whitespace"
            )
        for name in ("objective", "acceptance_criteria", "constraints"):
            if len(getattr(self, name)) > _MAX_REQUIREMENT_CHARS:
                raise RequirementTraceabilityError(
                    f"{name} exceeds {_MAX_REQUIREMENT_CHARS} characters"
                )

    def canonical(self) -> dict[str, str]:
        return {
            "objective": self.objective,
            "acceptance_criteria": self.acceptance_criteria,
            "constraints": self.constraints,
        }


def canonical_planning_fingerprint(
    provenance: Mapping[str, str],
    requirements: PlanningRequirements,
) -> str:
    """Reproduce dashboard Project Planning fingerprinting exactly."""
    canonical_provenance = _canonical_planning_provenance(provenance)
    return canonical_digest(
        {
            "schema_version": 1,
            "provenance": canonical_provenance,
            "requirements": requirements.canonical(),
        }
    )


@dataclass(frozen=True, order=True)
class RequirementSource:
    """One exact human-declared source item from the planning request."""

    plan_request_fingerprint: str
    kind: RequirementKind
    text: str
    requirement_id: str = field(init=False, compare=True)

    def __post_init__(self) -> None:
        _require_digest(self.plan_request_fingerprint, "plan_request_fingerprint")
        if not isinstance(self.kind, RequirementKind):
            raise TypeError("kind must be a RequirementKind")
        if not isinstance(self.text, str) or not self.text or self.text != self.text.strip():
            raise RequirementTraceabilityError(
                "requirement source text must be canonical and non-empty"
            )
        if len(self.text) > _MAX_REQUIREMENT_CHARS:
            raise RequirementTraceabilityError("requirement source text is too long")
        object.__setattr__(
            self,
            "requirement_id",
            canonical_digest(
                {
                    "schema_version": TRACEABILITY_SCHEMA_VERSION,
                    "plan_request_fingerprint": self.plan_request_fingerprint,
                    "kind": self.kind.value,
                    "text": self.text,
                }
            ),
        )

    def canonical(self) -> dict[str, object]:
        return {
            "requirement_id": self.requirement_id,
            "kind": self.kind.value,
            "text": self.text,
        }


@dataclass(frozen=True, order=True)
class CoverageClaim:
    """Human-declared trace links whose referenced IDs are server-validated."""

    kind: RequirementKind
    artifact_paths: tuple[str, ...] = ()
    evidence_ids: tuple[str, ...] = ()
    rationale: str = ""

    def __post_init__(self) -> None:
        if not isinstance(self.kind, RequirementKind):
            raise TypeError("kind must be a RequirementKind")
        paths = tuple(sorted(_validate_repository_path(item) for item in self.artifact_paths))
        if len(paths) != len(set(paths)):
            raise RequirementTraceabilityError("artifact paths must be unique")
        evidence = tuple(sorted(self.evidence_ids))
        if len(evidence) != len(set(evidence)):
            raise RequirementTraceabilityError("evidence IDs must be unique")
        for evidence_id in evidence:
            _require_digest(evidence_id, "evidence_id")
        if not isinstance(self.rationale, str) or self.rationale != self.rationale.strip():
            raise RequirementTraceabilityError(
                "coverage rationale must be canonical text without outer whitespace"
            )
        if len(self.rationale) > _MAX_RATIONALE_CHARS:
            raise RequirementTraceabilityError(
                f"coverage rationale exceeds {_MAX_RATIONALE_CHARS} characters"
            )
        object.__setattr__(self, "artifact_paths", paths)
        object.__setattr__(self, "evidence_ids", evidence)

    @property
    def linked(self) -> bool:
        return bool(self.artifact_paths)

    @property
    def evidenced(self) -> bool:
        return bool(self.artifact_paths and self.evidence_ids)

    def canonical(self, *, requirement_id: str) -> dict[str, object]:
        _require_digest(requirement_id, "requirement_id")
        return {
            "requirement_id": requirement_id,
            "kind": self.kind.value,
            "artifact_paths": list(self.artifact_paths),
            "evidence_ids": list(self.evidence_ids),
            "rationale": self.rationale,
            "linked": self.linked,
            "evidenced": self.evidenced,
        }


@dataclass(frozen=True)
class RequirementTraceabilityManifest:
    """Content-addressed traceability artifact with no semantic/release authority."""

    organization_id: str
    repository: str
    certificate_id: str
    candidate_id: str
    plan_id: str
    plan_request_fingerprint: str
    planning_provenance: tuple[tuple[str, str], ...]
    requirements: tuple[RequirementSource, ...]
    claims: tuple[CoverageClaim, ...]
    created_by: str
    created_at: datetime
    manifest_id: str = field(init=False)

    def __post_init__(self) -> None:
        for name in ("organization_id", "repository", "plan_id", "created_by"):
            _require_text(getattr(self, name), name)
        for name in ("certificate_id", "candidate_id", "plan_request_fingerprint"):
            _require_digest(getattr(self, name), name)
        if not isinstance(self.created_at, datetime) or self.created_at.tzinfo is None:
            raise RequirementTraceabilityError("created_at must be timezone-aware")
        provenance = tuple(sorted(self.planning_provenance))
        if len(provenance) != len({key for key, _ in provenance}):
            raise RequirementTraceabilityError("planning provenance keys must be unique")
        _canonical_planning_provenance(dict(provenance))
        requirements = tuple(sorted(self.requirements, key=lambda item: item.kind.value))
        claims = tuple(sorted(self.claims, key=lambda item: item.kind.value))
        if any(not isinstance(item, RequirementSource) for item in requirements):
            raise TypeError("requirements must contain RequirementSource values")
        if any(not isinstance(item, CoverageClaim) for item in claims):
            raise TypeError("claims must contain CoverageClaim values")
        requirement_kinds = tuple(item.kind for item in requirements)
        claim_kinds = tuple(item.kind for item in claims)
        if len(requirement_kinds) != len(set(requirement_kinds)):
            raise RequirementTraceabilityError("requirement kinds must be unique")
        if len(claim_kinds) != len(set(claim_kinds)):
            raise RequirementTraceabilityError("coverage claim kinds must be unique")
        if set(requirement_kinds) != set(claim_kinds):
            raise RequirementTraceabilityError(
                "every requirement source requires exactly one coverage claim"
            )
        if {
            RequirementKind.OBJECTIVE,
            RequirementKind.ACCEPTANCE_CRITERIA,
        } - set(requirement_kinds):
            raise RequirementTraceabilityError(
                "objective and acceptance criteria are mandatory traceability sources"
            )
        object.__setattr__(self, "planning_provenance", provenance)
        object.__setattr__(self, "requirements", requirements)
        object.__setattr__(self, "claims", claims)
        object.__setattr__(
            self,
            "manifest_id",
            canonical_digest(self.canonical(include_id=False)),
        )

    @property
    def status(self) -> TraceCoverageStatus:
        return (
            TraceCoverageStatus.COMPLETE
            if all(item.linked for item in self.claims)
            else TraceCoverageStatus.PARTIAL
        )

    @property
    def semantic_result(self) -> None:
        return None

    @property
    def release_authority(self) -> bool:
        return False

    def canonical(self, *, include_id: bool = True) -> dict[str, object]:
        sources = {item.kind: item for item in self.requirements}
        claims = {item.kind: item for item in self.claims}
        links = [
            claims[kind].canonical(requirement_id=sources[kind].requirement_id)
            for kind in sorted(sources, key=lambda value: value.value)
        ]
        linked_count = sum(1 for item in self.claims if item.linked)
        evidenced_count = sum(1 for item in self.claims if item.evidenced)
        payload: dict[str, object] = {
            "schema_version": TRACEABILITY_SCHEMA_VERSION,
            "organization_id": self.organization_id,
            "repository": self.repository,
            "certificate_id": self.certificate_id,
            "candidate_id": self.candidate_id,
            "plan_id": self.plan_id,
            "plan_request_fingerprint": self.plan_request_fingerprint,
            "planning_provenance": dict(self.planning_provenance),
            "requirements": [item.canonical() for item in self.requirements],
            "links": links,
            "status": self.status.value,
            "reference_integrity_verified": True,
            "authoritative": False,
            "semantic_result": None,
            "release_authority": False,
            "summary": {
                "total": len(self.requirements),
                "linked": linked_count,
                "evidenced": evidenced_count,
            },
            "created_by": self.created_by,
            "created_at": self.created_at.astimezone(timezone.utc).isoformat(),
        }
        if include_id:
            payload["manifest_id"] = self.manifest_id
        return payload


def requirement_sources(
    *,
    plan_request_fingerprint: str,
    requirements: PlanningRequirements,
) -> tuple[RequirementSource, ...]:
    """Derive the exact source set without interpreting free-form requirement text."""
    values = [
        (RequirementKind.OBJECTIVE, requirements.objective),
        (RequirementKind.ACCEPTANCE_CRITERIA, requirements.acceptance_criteria),
    ]
    if requirements.constraints:
        values.append((RequirementKind.CONSTRAINTS, requirements.constraints))
    return tuple(
        RequirementSource(
            plan_request_fingerprint=plan_request_fingerprint,
            kind=kind,
            text=text,
        )
        for kind, text in values
    )


def build_requirement_traceability_manifest(
    *,
    certificate: DeliveryCertificate,
    candidate: DeliveryVerificationCandidate,
    plan_id: str,
    planning_provenance: Mapping[str, str],
    requirements: PlanningRequirements,
    claims: tuple[CoverageClaim, ...],
    created_by: str,
    created_at: datetime | None = None,
) -> RequirementTraceabilityManifest:
    """Validate exact upstream identities and bounded trace references."""
    if not isinstance(certificate, DeliveryCertificate):
        raise TypeError("certificate must be a DeliveryCertificate")
    if not isinstance(candidate, DeliveryVerificationCandidate):
        raise TypeError("candidate must be a DeliveryVerificationCandidate")
    if certificate.result is not DeliveryCertificationResult.PASS:
        raise RequirementTraceabilityError(
            "requirement traceability requires a PASS delivery certificate"
        )
    if certificate.candidate_id != candidate.candidate_id:
        raise RequirementTraceabilityError("certificate does not bind the candidate")
    if (
        certificate.organization_id != candidate.organization_id
        or certificate.repository != candidate.repository
    ):
        raise RequirementTraceabilityError("certificate tenant/repository binding drifted")
    _require_text(plan_id, "plan_id")
    if plan_id != candidate.plan_id:
        raise RequirementTraceabilityError("plan_id does not match delivery candidate")

    canonical_provenance = _canonical_planning_provenance(planning_provenance)
    expected_candidate_values = {
        "intent_id": candidate.intent_id,
        "content_fingerprint": candidate.onboarding_content_fingerprint,
        "report_id": candidate.audit_report_id,
        "audit_request_fingerprint": candidate.audit_request_fingerprint,
        "manifest_id": candidate.audit_manifest_id,
        "evidence_bundle_id": candidate.audit_evidence_bundle_id,
        "commit_sha": candidate.audit_commit_sha,
        "repository": candidate.repository,
    }
    for key, expected in expected_candidate_values.items():
        if canonical_provenance[key] != expected:
            raise RequirementTraceabilityError(
                f"planning provenance {key} does not match delivery candidate"
            )
    plan_fingerprint = canonical_planning_fingerprint(
        canonical_provenance,
        requirements,
    )
    if plan_fingerprint != candidate.plan_request_fingerprint:
        raise RequirementTraceabilityError(
            "requirements + planning provenance do not match candidate plan fingerprint"
        )

    sources = requirement_sources(
        plan_request_fingerprint=plan_fingerprint,
        requirements=requirements,
    )
    claim_by_kind = {item.kind: item for item in claims}
    if len(claim_by_kind) != len(claims) or set(claim_by_kind) != {item.kind for item in sources}:
        raise RequirementTraceabilityError(
            "coverage claims must exactly match the requirement source kinds"
        )
    allowed_paths = {item.path for item in candidate.files}
    allowed_evidence = set(candidate.evidence_ids)
    for claim in claims:
        if not set(claim.artifact_paths) <= allowed_paths:
            raise RequirementTraceabilityError(
                f"{claim.kind.value} references paths outside the certified artifact"
            )
        if not set(claim.evidence_ids) <= allowed_evidence:
            raise RequirementTraceabilityError(
                f"{claim.kind.value} references evidence outside the certified candidate"
            )

    return RequirementTraceabilityManifest(
        organization_id=candidate.organization_id,
        repository=candidate.repository,
        certificate_id=certificate.certificate_id,
        candidate_id=candidate.candidate_id,
        plan_id=plan_id,
        plan_request_fingerprint=plan_fingerprint,
        planning_provenance=tuple(canonical_provenance.items()),
        requirements=sources,
        claims=claims,
        created_by=created_by,
        created_at=created_at or datetime.now(timezone.utc),
    )


def parse_requirement_traceability_manifest(
    payload: Mapping[str, Any],
) -> RequirementTraceabilityManifest:
    """Reconstruct and content-verify a serialized manifest."""
    if not isinstance(payload, Mapping):
        raise RequirementTraceabilityError("traceability manifest must be an object")
    raw = dict(payload)
    expected_keys = {
        "schema_version",
        "organization_id",
        "repository",
        "certificate_id",
        "candidate_id",
        "plan_id",
        "plan_request_fingerprint",
        "planning_provenance",
        "requirements",
        "links",
        "status",
        "reference_integrity_verified",
        "authoritative",
        "semantic_result",
        "release_authority",
        "summary",
        "created_by",
        "created_at",
        "manifest_id",
    }
    if set(raw) != expected_keys or raw.get("schema_version") != TRACEABILITY_SCHEMA_VERSION:
        raise RequirementTraceabilityError("unsupported traceability manifest schema")
    provenance = raw.get("planning_provenance")
    raw_sources = raw.get("requirements")
    raw_links = raw.get("links")
    if not isinstance(provenance, Mapping) or not isinstance(raw_sources, list) or not isinstance(raw_links, list):
        raise RequirementTraceabilityError("traceability manifest collections are malformed")
    try:
        source_by_kind: dict[RequirementKind, RequirementSource] = {}
        for item in raw_sources:
            if not isinstance(item, Mapping):
                raise RequirementTraceabilityError("requirement source is malformed")
            kind = RequirementKind(str(item["kind"]))
            source = RequirementSource(
                plan_request_fingerprint=str(raw["plan_request_fingerprint"]),
                kind=kind,
                text=str(item["text"]),
            )
            if item.get("requirement_id") != source.requirement_id:
                raise RequirementTraceabilityError("requirement_id content identity mismatch")
            source_by_kind[kind] = source
        claims: list[CoverageClaim] = []
        for item in raw_links:
            if not isinstance(item, Mapping):
                raise RequirementTraceabilityError("coverage link is malformed")
            kind = RequirementKind(str(item["kind"]))
            source = source_by_kind[kind]
            if item.get("requirement_id") != source.requirement_id:
                raise RequirementTraceabilityError("coverage link requirement_id mismatch")
            claim = CoverageClaim(
                kind=kind,
                artifact_paths=tuple(item.get("artifact_paths") or ()),
                evidence_ids=tuple(item.get("evidence_ids") or ()),
                rationale=str(item.get("rationale") or ""),
            )
            if item.get("linked") is not claim.linked or item.get("evidenced") is not claim.evidenced:
                raise RequirementTraceabilityError("coverage link derived flags are invalid")
            claims.append(claim)
        manifest = RequirementTraceabilityManifest(
            organization_id=str(raw["organization_id"]),
            repository=str(raw["repository"]),
            certificate_id=str(raw["certificate_id"]),
            candidate_id=str(raw["candidate_id"]),
            plan_id=str(raw["plan_id"]),
            plan_request_fingerprint=str(raw["plan_request_fingerprint"]),
            planning_provenance=tuple((str(key), str(value)) for key, value in provenance.items()),
            requirements=tuple(source_by_kind.values()),
            claims=tuple(claims),
            created_by=str(raw["created_by"]),
            created_at=datetime.fromisoformat(str(raw["created_at"])),
        )
    except (KeyError, TypeError, ValueError) as exc:
        if isinstance(exc, RequirementTraceabilityError):
            raise
        raise RequirementTraceabilityError(str(exc)) from exc
    if raw != manifest.canonical():
        raise RequirementTraceabilityError("traceability manifest content identity mismatch")
    return manifest


def _canonical_planning_provenance(provenance: Mapping[str, str]) -> dict[str, str]:
    if not isinstance(provenance, Mapping) or set(provenance) != _PLANNING_PROVENANCE_KEYS:
        raise RequirementTraceabilityError(
            "planning provenance fields do not match the canonical planning contract"
        )
    canonical: dict[str, str] = {}
    for key in sorted(_PLANNING_PROVENANCE_KEYS):
        value = provenance.get(key)
        if not isinstance(value, str) or not value or value != value.strip():
            raise RequirementTraceabilityError(
                f"planning provenance {key} must be canonical non-empty text"
            )
        canonical[key] = value
    return canonical


def _validate_repository_path(value: str) -> str:
    if not isinstance(value, str) or not value or value != value.strip() or "\\" in value:
        raise RequirementTraceabilityError("artifact path must be canonical POSIX text")
    path = PurePosixPath(value)
    if path.is_absolute() or path.as_posix() != value:
        raise RequirementTraceabilityError("artifact path must be repository-relative POSIX")
    if any(part in {"", ".", ".."} for part in path.parts):
        raise RequirementTraceabilityError("artifact path cannot contain traversal")
    return value


def _require_digest(value: object, name: str) -> str:
    if not isinstance(value, str) or not _HEX64.fullmatch(value):
        raise RequirementTraceabilityError(f"{name} must be a lowercase SHA-256 digest")
    return value


def _require_text(value: object, name: str) -> str:
    if not isinstance(value, str) or not value or value != value.strip():
        raise RequirementTraceabilityError(f"{name} must be canonical non-empty text")
    return value


__all__ = [
    "CoverageClaim",
    "PlanningRequirements",
    "RequirementKind",
    "RequirementSource",
    "RequirementTraceabilityError",
    "RequirementTraceabilityManifest",
    "TRACEABILITY_SCHEMA_VERSION",
    "TraceCoverageStatus",
    "build_requirement_traceability_manifest",
    "canonical_planning_fingerprint",
    "parse_requirement_traceability_manifest",
    "requirement_sources",
]
