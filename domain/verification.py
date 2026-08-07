"""Independent, deterministic verification contracts for P3-20."""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from typing import Any

from domain.distribution import DispatchRecord


class VerificationError(ValueError):
    """Raised when a verification request cannot be safely evaluated."""


EVIDENCE_KINDS = ("test", "audit", "security", "architecture", "requirements", "provenance")


@dataclass(frozen=True)
class Evidence:
    kind: str
    evidence_id: str
    passed: bool
    statement: str
    package_fingerprint: str
    contract_fingerprint: str
    dispatch_fingerprint: str
    artifact_fingerprint: str

    def __post_init__(self) -> None:
        if self.kind not in EVIDENCE_KINDS:
            raise VerificationError(f"Unsupported evidence kind: {self.kind}")
        for name, value in (("evidence_id", self.evidence_id), ("statement", self.statement),
                            ("package_fingerprint", self.package_fingerprint),
                            ("contract_fingerprint", self.contract_fingerprint),
                            ("dispatch_fingerprint", self.dispatch_fingerprint),
                            ("artifact_fingerprint", self.artifact_fingerprint)):
            if not isinstance(value, str) or not value.strip():
                raise VerificationError(f"{name} must be non-empty")


@dataclass(frozen=True)
class DeliveredProduct:
    artifact_id: str
    artifact_fingerprint: str
    output_names: tuple[str, ...]
    evidence: tuple[Evidence, ...]

    def __post_init__(self) -> None:
        if not self.artifact_id.strip() or not self.artifact_fingerprint.strip():
            raise VerificationError("Delivered product identity must be non-empty")
        if not self.output_names:
            raise VerificationError("Delivered product must declare outputs")
        if len(self.output_names) != len(set(self.output_names)):
            raise VerificationError("Delivered product outputs must be unique")


@dataclass(frozen=True)
class VerificationCheck:
    check_id: str
    passed: bool
    statement: str


@dataclass(frozen=True)
class VerificationResult:
    verification_id: str
    status: str
    package_fingerprint: str
    contract_fingerprint: str
    dispatch_fingerprint: str
    artifact_fingerprint: str
    checks: tuple[VerificationCheck, ...]
    evidence_ids: tuple[str, ...]
    failures: tuple[str, ...]

    def __post_init__(self) -> None:
        if self.status not in ("PASS", "FAIL"):
            raise VerificationError("Verification status must be PASS or FAIL")
        if self.status == "PASS" and self.failures:
            raise VerificationError("PASS result cannot contain failures")
        if self.status == "FAIL" and not self.failures:
            raise VerificationError("FAIL result requires failures")

    @property
    def fingerprint(self) -> str:
        payload: dict[str, Any] = {
            "verification_id": self.verification_id,
            "status": self.status,
            "package_fingerprint": self.package_fingerprint,
            "contract_fingerprint": self.contract_fingerprint,
            "dispatch_fingerprint": self.dispatch_fingerprint,
            "artifact_fingerprint": self.artifact_fingerprint,
            "checks": [(c.check_id, c.passed, c.statement) for c in self.checks],
            "evidence_ids": list(self.evidence_ids),
            "failures": list(self.failures),
        }
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
        return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def verification_id(dispatch: DispatchRecord, product: DeliveredProduct) -> str:
    payload = {
        "dispatch_fingerprint": dispatch.fingerprint,
        "artifact_fingerprint": product.artifact_fingerprint,
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return "verification-" + hashlib.sha256(encoded.encode("utf-8")).hexdigest()[:24]
