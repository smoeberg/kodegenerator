"""Architecture Contract v1 — machine-evaluable architecture rules.

Extends the Phase 3 ArchitectureContract foundation with structural layers,
dependency rules, constraints, quality gates, and content fingerprinting.

Only human-approved contracts may authorize downstream codegen/verification.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import hashlib
import json
from typing import Any, Mapping


class ArchitectureContractV1Error(ValueError):
    """Raised when an architecture contract v1 document is invalid."""


_ALLOWED_STATUS = frozenset({"draft", "review", "approved", "superseded", "rejected"})
_ALLOWED_STYLES = frozenset(
    {"hexagonal", "clean", "modular_monolith", "microservices", "layered", "other"}
)
_ALLOWED_SEVERITY = frozenset({"block", "warn", "info"})
_ALLOWED_LANGUAGES = frozenset({"python", "typescript", "go", "java", "csharp", "other"})
_ALLOWED_CONSTRAINT_TYPES = frozenset(
    {
        "forbid_pattern",
        "require_pattern",
        "require_auth_on_routes",
        "no_path_traversal_writes",
        "no_cross_module_db_access",
        "max_module_fanout",
        "allowlisted_dependencies_only",
        "custom",
    }
)
_ALLOWED_GATE_TYPES = frozenset(
    {
        "command",
        "architecture_tests",
        "openapi_conformance",
        "event_schema_conformance",
        "dependency_rules",
        "security_scan",
        "custom",
    }
)
_ALLOWED_TRACE_RELATIONS = frozenset(
    {"implements", "constrains", "satisfies", "derived_from", "verifies"}
)


def _require_nonempty_str(name: str, value: Any) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ArchitectureContractV1Error(f"{name} must be a non-empty string")
    return value.strip()


def _canonical_json(data: Mapping[str, Any]) -> str:
    return json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


@dataclass(frozen=True)
class LayerV1:
    id: str
    path: str
    description: str = ""
    framework_independent: bool | None = None

    def __post_init__(self) -> None:
        _require_nonempty_str("layer.id", self.id)
        _require_nonempty_str("layer.path", self.path)
        if "../" in self.path or self.path.startswith("/"):
            raise ArchitectureContractV1Error(f"layer.path must be repo-relative without traversal: {self.path}")

    def to_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {"id": self.id, "path": self.path}
        if self.description:
            data["description"] = self.description
        if self.framework_independent is not None:
            data["framework_independent"] = self.framework_independent
        return data

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "LayerV1":
        return cls(
            id=_require_nonempty_str("layer.id", data.get("id")),
            path=_require_nonempty_str("layer.path", data.get("path")),
            description=str(data.get("description") or ""),
            framework_independent=data.get("framework_independent"),
        )


@dataclass(frozen=True)
class DependencyRuleV1:
    id: str
    source: str
    may_depend_on: tuple[str, ...]
    severity: str = "block"
    description: str = ""

    def __post_init__(self) -> None:
        _require_nonempty_str("dependency_rule.id", self.id)
        _require_nonempty_str("dependency_rule.source", self.source)
        if self.severity not in _ALLOWED_SEVERITY:
            raise ArchitectureContractV1Error(f"Invalid severity: {self.severity}")
        if not self.id.startswith("DEP-"):
            raise ArchitectureContractV1Error(f"dependency_rule.id must start with DEP-: {self.id}")

    def allows(self, target_layer_id: str) -> bool:
        return target_layer_id in self.may_depend_on

    def to_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            "id": self.id,
            "source": self.source,
            "may_depend_on": list(self.may_depend_on),
            "severity": self.severity,
        }
        if self.description:
            data["description"] = self.description
        return data

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "DependencyRuleV1":
        targets = data.get("may_depend_on") or []
        if not isinstance(targets, list):
            raise ArchitectureContractV1Error("may_depend_on must be a list")
        return cls(
            id=_require_nonempty_str("dependency_rule.id", data.get("id")),
            source=_require_nonempty_str("dependency_rule.source", data.get("source")),
            may_depend_on=tuple(str(t) for t in targets),
            severity=str(data.get("severity") or "block"),
            description=str(data.get("description") or ""),
        )


@dataclass(frozen=True)
class ConstraintV1:
    id: str
    type: str
    severity: str = "block"
    description: str = ""
    pattern: str | None = None
    scope: tuple[str, ...] = ()
    params: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _require_nonempty_str("constraint.id", self.id)
        if self.type not in _ALLOWED_CONSTRAINT_TYPES:
            raise ArchitectureContractV1Error(f"Invalid constraint type: {self.type}")
        if self.severity not in _ALLOWED_SEVERITY:
            raise ArchitectureContractV1Error(f"Invalid severity: {self.severity}")
        if self.type in {"forbid_pattern", "require_pattern"} and not self.pattern:
            raise ArchitectureContractV1Error(f"{self.type} requires pattern")

    def to_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            "id": self.id,
            "type": self.type,
            "severity": self.severity,
        }
        if self.description:
            data["description"] = self.description
        if self.pattern is not None:
            data["pattern"] = self.pattern
        if self.scope:
            data["scope"] = list(self.scope)
        if self.params:
            data["params"] = dict(self.params)
        return data

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ConstraintV1":
        scope = data.get("scope") or []
        params = data.get("params") or {}
        if not isinstance(scope, list):
            raise ArchitectureContractV1Error("constraint.scope must be a list")
        if not isinstance(params, Mapping):
            raise ArchitectureContractV1Error("constraint.params must be an object")
        return cls(
            id=_require_nonempty_str("constraint.id", data.get("id")),
            type=_require_nonempty_str("constraint.type", data.get("type")),
            severity=str(data.get("severity") or "block"),
            description=str(data.get("description") or ""),
            pattern=data.get("pattern"),
            scope=tuple(str(s) for s in scope),
            params=dict(params),
        )


@dataclass(frozen=True)
class QualityGateV1:
    id: str
    type: str
    required: bool = True
    command: str | None = None
    timeout_seconds: int | None = None
    description: str = ""

    def __post_init__(self) -> None:
        _require_nonempty_str("quality_gate.id", self.id)
        if self.type not in _ALLOWED_GATE_TYPES:
            raise ArchitectureContractV1Error(f"Invalid quality_gate type: {self.type}")
        if self.type == "command" and not self.command:
            raise ArchitectureContractV1Error("command quality_gate requires command")

    def to_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            "id": self.id,
            "type": self.type,
            "required": self.required,
        }
        if self.command is not None:
            data["command"] = self.command
        if self.timeout_seconds is not None:
            data["timeout_seconds"] = self.timeout_seconds
        if self.description:
            data["description"] = self.description
        return data

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "QualityGateV1":
        timeout = data.get("timeout_seconds")
        if timeout is not None and not isinstance(timeout, int):
            raise ArchitectureContractV1Error("timeout_seconds must be an integer")
        return cls(
            id=_require_nonempty_str("quality_gate.id", data.get("id")),
            type=_require_nonempty_str("quality_gate.type", data.get("type")),
            required=bool(data.get("required", True)),
            command=data.get("command"),
            timeout_seconds=timeout,
            description=str(data.get("description") or ""),
        )


@dataclass(frozen=True)
class DecisionV1:
    id: str
    decision: str
    rationale: str
    constraints: tuple[str, ...] = ()
    requirement_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _require_nonempty_str("decision.id", self.id)
        _require_nonempty_str("decision.decision", self.decision)
        _require_nonempty_str("decision.rationale", self.rationale)

    def to_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            "id": self.id,
            "decision": self.decision,
            "rationale": self.rationale,
        }
        if self.constraints:
            data["constraints"] = list(self.constraints)
        if self.requirement_ids:
            data["requirement_ids"] = list(self.requirement_ids)
        return data

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "DecisionV1":
        constraints = data.get("constraints") or []
        requirement_ids = data.get("requirement_ids") or []
        return cls(
            id=_require_nonempty_str("decision.id", data.get("id")),
            decision=_require_nonempty_str("decision.decision", data.get("decision")),
            rationale=_require_nonempty_str("decision.rationale", data.get("rationale")),
            constraints=tuple(str(c) for c in constraints),
            requirement_ids=tuple(str(r) for r in requirement_ids),
        )


@dataclass(frozen=True)
class TraceLinkV1:
    source_id: str
    target_id: str
    relation: str

    def __post_init__(self) -> None:
        _require_nonempty_str("trace.source_id", self.source_id)
        _require_nonempty_str("trace.target_id", self.target_id)
        if self.relation not in _ALLOWED_TRACE_RELATIONS:
            raise ArchitectureContractV1Error(f"Invalid trace relation: {self.relation}")

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_id": self.source_id,
            "target_id": self.target_id,
            "relation": self.relation,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "TraceLinkV1":
        return cls(
            source_id=_require_nonempty_str("trace.source_id", data.get("source_id")),
            target_id=_require_nonempty_str("trace.target_id", data.get("target_id")),
            relation=_require_nonempty_str("trace.relation", data.get("relation")),
        )


@dataclass(frozen=True)
class ApprovalV1:
    status: str
    contract_id: str | None = None
    version: str | None = None
    content_fingerprint: str | None = None
    approver_id: str | None = None
    approved_at: datetime | None = None
    validation_result: str | None = None

    def __post_init__(self) -> None:
        if self.status not in {"pending", "approved", "rejected"}:
            raise ArchitectureContractV1Error(f"Invalid approval status: {self.status}")
        if self.status == "approved":
            if not self.approver_id or not self.approved_at or not self.content_fingerprint:
                raise ArchitectureContractV1Error(
                    "approved approval requires approver_id, approved_at, content_fingerprint"
                )

    def to_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {"status": self.status}
        if self.contract_id is not None:
            data["contract_id"] = self.contract_id
        if self.version is not None:
            data["version"] = self.version
        if self.content_fingerprint is not None:
            data["content_fingerprint"] = self.content_fingerprint
        if self.approver_id is not None:
            data["approver_id"] = self.approver_id
        if self.approved_at is not None:
            data["approved_at"] = self.approved_at.isoformat()
        if self.validation_result is not None:
            data["validation_result"] = self.validation_result
        return data

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ApprovalV1":
        approved_at_raw = data.get("approved_at")
        approved_at: datetime | None = None
        if approved_at_raw:
            approved_at = datetime.fromisoformat(str(approved_at_raw).replace("Z", "+00:00"))
        return cls(
            status=_require_nonempty_str("approval.status", data.get("status")),
            contract_id=data.get("contract_id"),
            version=data.get("version"),
            content_fingerprint=data.get("content_fingerprint"),
            approver_id=data.get("approver_id"),
            approved_at=approved_at,
            validation_result=data.get("validation_result"),
        )


@dataclass(frozen=True)
class ArchitectureContractV1:
    """Machine-evaluable architecture contract (schema_version 1.0)."""

    schema_version: str
    contract_id: str
    version: str
    status: str
    project_name: str
    style: str
    layers: tuple[LayerV1, ...]
    dependency_rules: tuple[DependencyRuleV1, ...]
    quality_gates: tuple[QualityGateV1, ...]
    constraints: tuple[ConstraintV1, ...] = ()
    decisions: tuple[DecisionV1, ...] = ()
    traceability: tuple[TraceLinkV1, ...] = ()
    technology_constraints: tuple[str, ...] = ()
    language: str | None = None
    runtime: str | None = None
    approval: ApprovalV1 = field(default_factory=lambda: ApprovalV1(status="pending"))

    def __post_init__(self) -> None:
        if self.schema_version != "1.0":
            raise ArchitectureContractV1Error(f"Unsupported schema_version: {self.schema_version}")
        _require_nonempty_str("contract_id", self.contract_id)
        _require_nonempty_str("version", self.version)
        _require_nonempty_str("project_name", self.project_name)
        if self.status not in _ALLOWED_STATUS:
            raise ArchitectureContractV1Error(f"Invalid status: {self.status}")
        if self.style not in _ALLOWED_STYLES:
            raise ArchitectureContractV1Error(f"Invalid style: {self.style}")
        if not self.layers:
            raise ArchitectureContractV1Error("At least one layer is required")
        if not self.dependency_rules:
            raise ArchitectureContractV1Error("At least one dependency_rule is required")
        if not self.quality_gates:
            raise ArchitectureContractV1Error("At least one quality_gate is required")
        layer_ids = [layer.id for layer in self.layers]
        if len(layer_ids) != len(set(layer_ids)):
            raise ArchitectureContractV1Error("Layer ids must be unique")
        rule_ids = [rule.id for rule in self.dependency_rules]
        if len(rule_ids) != len(set(rule_ids)):
            raise ArchitectureContractV1Error("Dependency rule ids must be unique")
        known = set(layer_ids)
        for rule in self.dependency_rules:
            if rule.source not in known:
                raise ArchitectureContractV1Error(
                    f"dependency_rule {rule.id} source unknown layer: {rule.source}"
                )
            for target in rule.may_depend_on:
                if target not in known:
                    raise ArchitectureContractV1Error(
                        f"dependency_rule {rule.id} may_depend_on unknown layer: {target}"
                    )
        if self.language is not None and self.language not in _ALLOWED_LANGUAGES:
            raise ArchitectureContractV1Error(f"Invalid language: {self.language}")
        if self.status == "approved":
            if self.approval.status != "approved":
                raise ArchitectureContractV1Error("Approved contract requires approval.status=approved")
            if self.approval.content_fingerprint != self.fingerprint:
                raise ArchitectureContractV1Error(
                    "approval.content_fingerprint must match contract fingerprint"
                )

    def canonical_dict(self) -> dict[str, Any]:
        """Immutable architecture content excluding approval workflow metadata."""
        project: dict[str, Any] = {"name": self.project_name}
        if self.language is not None:
            project["language"] = self.language
        if self.runtime is not None:
            project["runtime"] = self.runtime
        return {
            "schema_version": self.schema_version,
            "contract_id": self.contract_id,
            "version": self.version,
            "project": project,
            "style": self.style,
            "layers": [layer.to_dict() for layer in self.layers],
            "dependency_rules": [rule.to_dict() for rule in self.dependency_rules],
            "constraints": [c.to_dict() for c in self.constraints],
            "quality_gates": [g.to_dict() for g in self.quality_gates],
            "decisions": [d.to_dict() for d in self.decisions],
            "technology_constraints": list(self.technology_constraints),
            "traceability": [t.to_dict() for t in self.traceability],
        }

    @property
    def fingerprint(self) -> str:
        encoded = _canonical_json(self.canonical_dict())
        return hashlib.sha256(encoded.encode("utf-8")).hexdigest()

    def rule_for_source(self, layer_id: str) -> DependencyRuleV1 | None:
        for rule in self.dependency_rules:
            if rule.source == layer_id:
                return rule
        return None

    def approve(self, approver_id: str, approved_at: datetime | None = None) -> "ArchitectureContractV1":
        """Return a new human-approved contract; never mutate the proposal."""
        if self.status not in {"draft", "review"}:
            raise ArchitectureContractV1Error("Only draft/review contracts may be approved")
        approver = _require_nonempty_str("approver_id", approver_id)
        when = approved_at or datetime.now(timezone.utc)
        approval = ApprovalV1(
            status="approved",
            contract_id=self.contract_id,
            version=self.version,
            content_fingerprint=self.fingerprint,
            approver_id=approver,
            approved_at=when,
            validation_result="schema_and_invariants_ok",
        )
        return ArchitectureContractV1(
            schema_version=self.schema_version,
            contract_id=self.contract_id,
            version=self.version,
            status="approved",
            project_name=self.project_name,
            style=self.style,
            layers=self.layers,
            dependency_rules=self.dependency_rules,
            quality_gates=self.quality_gates,
            constraints=self.constraints,
            decisions=self.decisions,
            traceability=self.traceability,
            technology_constraints=self.technology_constraints,
            language=self.language,
            runtime=self.runtime,
            approval=approval,
        )

    def to_dict(self) -> dict[str, Any]:
        data = self.canonical_dict()
        data["status"] = self.status
        data["approval"] = self.approval.to_dict()
        data["content_fingerprint"] = self.fingerprint
        return data

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ArchitectureContractV1":
        project = data.get("project") or {}
        if not isinstance(project, Mapping):
            raise ArchitectureContractV1Error("project must be an object")
        layers = tuple(LayerV1.from_dict(item) for item in (data.get("layers") or []))
        rules = tuple(DependencyRuleV1.from_dict(item) for item in (data.get("dependency_rules") or []))
        constraints = tuple(ConstraintV1.from_dict(item) for item in (data.get("constraints") or []))
        gates = tuple(QualityGateV1.from_dict(item) for item in (data.get("quality_gates") or []))
        decisions = tuple(DecisionV1.from_dict(item) for item in (data.get("decisions") or []))
        traces = tuple(TraceLinkV1.from_dict(item) for item in (data.get("traceability") or []))
        tech = tuple(str(t) for t in (data.get("technology_constraints") or []))
        approval_raw = data.get("approval") or {"status": "pending"}
        approval = ApprovalV1.from_dict(approval_raw)
        return cls(
            schema_version=str(data.get("schema_version") or ""),
            contract_id=_require_nonempty_str("contract_id", data.get("contract_id")),
            version=_require_nonempty_str("version", data.get("version")),
            status=_require_nonempty_str("status", data.get("status")),
            project_name=_require_nonempty_str("project.name", project.get("name")),
            style=_require_nonempty_str("style", data.get("style")),
            layers=layers,
            dependency_rules=rules,
            quality_gates=gates,
            constraints=constraints,
            decisions=decisions,
            traceability=traces,
            technology_constraints=tech,
            language=project.get("language"),
            runtime=project.get("runtime"),
            approval=approval,
        )
