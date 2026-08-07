"""Human-approved architecture contract for P3-18.

The architecture contract is the boundary between architecture design and
execution. An AI may propose it, but downstream agents only consume a contract
that has been explicitly approved by a human.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
from typing import Any, Mapping


class ArchitectureContractError(ValueError):
    """Raised when an architecture contract is unsafe or incomplete."""


@dataclass(frozen=True)
class ArchitectureDecision:
    id: str
    decision: str
    rationale: str
    constraints: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        for name, value in (("id", self.id), ("decision", self.decision), ("rationale", self.rationale)):
            if not isinstance(value, str) or not value.strip():
                raise ArchitectureContractError(f"{name} must be non-empty")


@dataclass(frozen=True)
class ArchitectureContract:
    schema_version: str
    contract_id: str
    version: str
    status: str
    style: str
    components: tuple[str, ...]
    boundaries: tuple[str, ...] = ()
    decisions: tuple[ArchitectureDecision, ...] = ()
    technology_constraints: tuple[str, ...] = ()
    forbidden_patterns: tuple[str, ...] = ()
    human_approved_by: str | None = None
    human_approved_at: datetime | None = None

    def __post_init__(self) -> None:
        for name, value in (("schema_version", self.schema_version), ("contract_id", self.contract_id),
                            ("version", self.version), ("style", self.style)):
            if not isinstance(value, str) or not value.strip():
                raise ArchitectureContractError(f"{name} must be non-empty")
        if self.status not in {"draft", "review", "approved", "superseded"}:
            raise ArchitectureContractError(f"Invalid architecture status: {self.status}")
        if not self.components:
            raise ArchitectureContractError("At least one architecture component is required")
        if self.status == "approved" and (not self.human_approved_by or not self.human_approved_at):
            raise ArchitectureContractError("Approved architecture requires human approval proof")

    def canonical_dict(self) -> dict[str, Any]:
        """Return immutable architecture content, excluding workflow approval metadata."""
        data = {
            "schema_version": self.schema_version,
            "contract_id": self.contract_id,
            "version": self.version,
            "style": self.style,
            "components": list(self.components),
            "boundaries": list(self.boundaries),
            "decisions": [
                {"id": d.id, "decision": d.decision, "rationale": d.rationale, "constraints": list(d.constraints)}
                for d in self.decisions
            ],
            "technology_constraints": list(self.technology_constraints),
            "forbidden_patterns": list(self.forbidden_patterns),
        }
        return data

    @property
    def fingerprint(self) -> str:
        encoded = json.dumps(self.canonical_dict(), sort_keys=True, separators=(",", ":"), ensure_ascii=True)
        return hashlib.sha256(encoded.encode("utf-8")).hexdigest()

    def approve(self, approver_id: str, approved_at: datetime | None = None) -> "ArchitectureContract":
        """Return a new human-approved contract; never mutate the proposal."""
        if self.status not in {"draft", "review"}:
            raise ArchitectureContractError("Only draft/review architecture contracts may be approved")
        if not approver_id.strip():
            raise ArchitectureContractError("approver_id must be non-empty")
        return ArchitectureContract(
            schema_version=self.schema_version,
            contract_id=self.contract_id,
            version=self.version,
            status="approved",
            style=self.style,
            components=self.components,
            boundaries=self.boundaries,
            decisions=self.decisions,
            technology_constraints=self.technology_constraints,
            forbidden_patterns=self.forbidden_patterns,
            human_approved_by=approver_id,
            human_approved_at=approved_at or datetime.now(timezone.utc),
        )
