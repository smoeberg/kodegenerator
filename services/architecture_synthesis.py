"""Deterministic architecture synthesis from approved requirements.

The engine deliberately does not call an LLM. It turns the canonical
requirements model into a machine-evaluable ArchitectureContractV1 and emits
explicit Decision objects when requirements leave an architectural trade-off
unresolved. Human approval remains a downstream gate.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import re
from typing import Iterable

from domain.architecture_contract_v1 import (
    ArchitectureContractV1,
    ConstraintV1,
    DecisionV1,
    DependencyRuleV1,
    LayerV1,
    QualityGateV1,
    TraceLinkV1,
)
from domain.decision import (
    Decision,
    DecisionAlternative,
    DecisionCategory,
    RiskLevel,
)
from domain.requirements import Requirement, RequirementsSpecification


@dataclass(frozen=True)
class ArchitectureSynthesisResult:
    """Synthesis output plus controller decisions requiring deliberation."""

    contract: ArchitectureContractV1
    decisions: tuple[Decision, ...] = ()
    interface_contracts: tuple[str, ...] = ()
    data_models: tuple[str, ...] = ()


class ArchitectureSynthesisEngine:
    """Synthesize a conservative clean/layered architecture from requirements."""

    def __init__(self, *, language: str = "python", runtime: str = "python3.12") -> None:
        if language not in {"python", "typescript", "go", "java", "csharp", "other"}:
            raise ValueError(f"Unsupported language: {language}")
        self.language = language
        self.runtime = runtime

    def synthesize(
        self,
        requirements: RequirementsSpecification,
        *,
        now: datetime | None = None,
    ) -> ArchitectureSynthesisResult:
        """Build a review-state contract and explicit unresolved decisions."""
        if requirements.status not in {"approved", "review"}:
            raise ValueError("Requirements must be approved or in review before architecture synthesis")

        timestamp = now or datetime.now(timezone.utc)
        project_name = str(requirements.project["name"])
        style = self._style(requirements)
        layers = self._layers(style)
        rules = self._dependency_rules(layers)
        constraints = self._constraints(requirements)
        interface_contracts = self._interface_contracts(requirements)
        data_models = self._data_models(requirements)
        dilemmas = self._dilemmas(requirements)

        contract_decisions = tuple(
            DecisionV1(
                id=f"ADR-{index:03d}",
                decision=d.question,
                rationale="Human/controller decision required before downstream execution.",
                requirement_ids=self._related_requirement_ids(requirements, d.question),
            )
            for index, d in enumerate(dilemmas, start=1)
        )
        traceability = tuple(
            TraceLinkV1(source_id=req.id, target_id=f"ARCH-{req.id}", relation="derived_from")
            for req in requirements.all_items()
            if isinstance(req, Requirement)
        )

        contract = ArchitectureContractV1(
            schema_version="1.0",
            contract_id=f"arch-{requirements.specification_id}",
            version=requirements.version,
            status="review",
            project_name=project_name,
            style=style,
            language=self.language,
            runtime=self.runtime,
            layers=layers,
            dependency_rules=rules,
            constraints=constraints,
            quality_gates=(
                QualityGateV1(id="QG-dependency-rules", type="dependency_rules", required=True),
                QualityGateV1(id="QG-architecture-tests", type="architecture_tests", required=True),
                QualityGateV1(id="QG-unit-tests", type="command", required=True, command="pytest -q"),
            ),
            decisions=contract_decisions,
            traceability=traceability,
            technology_constraints=(
                *interface_contracts,
                *data_models,
                *self._technology_constraints(requirements),
            ),
        )
        # Keep timestamp use explicit for deterministic callers and future audit hooks.
        _ = timestamp
        return ArchitectureSynthesisResult(
            contract=contract,
            decisions=tuple(dilemmas),
            interface_contracts=interface_contracts,
            data_models=data_models,
        )

    def _style(self, requirements: RequirementsSpecification) -> str:
        text = self._text(requirements)
        if any(term in text for term in ("microservice", "microservices", "service mesh")):
            return "microservices"
        if any(term in text for term in ("modular monolith", "module boundary")):
            return "modular_monolith"
        if any(term in text for term in ("hexagonal", "ports and adapters", "ports/adapters")):
            return "hexagonal"
        return "clean"

    @staticmethod
    def _layers(style: str) -> tuple[LayerV1, ...]:
        if style == "microservices":
            paths = (
                ("domain", "src/domain/**", True),
                ("application", "src/application/**", True),
                ("ports", "src/ports/**", True),
                ("adapters", "src/adapters/**", False),
                ("infrastructure", "src/infrastructure/**", False),
                ("tests", "tests/**", False),
            )
        else:
            paths = (
                ("domain", "src/domain/**", True),
                ("application", "src/application/**", True),
                ("ports", "src/ports/**", True),
                ("adapters", "src/adapters/**", False),
                ("infrastructure", "src/infrastructure/**", False),
                ("tests", "tests/**", False),
            )
        return tuple(
            LayerV1(id=layer_id, path=path, framework_independent=framework_independent)
            for layer_id, path, framework_independent in paths
        )

    @staticmethod
    def _dependency_rules(layers: tuple[LayerV1, ...]) -> tuple[DependencyRuleV1, ...]:
        known = {layer.id for layer in layers}
        targets = {
            "domain": (),
            "application": ("domain", "ports"),
            "ports": ("domain",),
            "adapters": ("application", "domain", "ports"),
            "infrastructure": ("application", "domain", "ports", "adapters"),
            "tests": tuple(layer.id for layer in layers if layer.id != "tests"),
        }
        return tuple(
            DependencyRuleV1(
                id=f"DEP-{index:03d}",
                source=layer.id,
                may_depend_on=tuple(target for target in targets.get(layer.id, ()) if target in known),
                severity="block",
                description=f"{layer.id} may depend only on explicitly allowed layers.",
            )
            for index, layer in enumerate(layers, start=1)
        )

    @staticmethod
    def _constraints(requirements: RequirementsSpecification) -> tuple[ConstraintV1, ...]:
        result: list[ConstraintV1] = [
            ConstraintV1(
                id="ARCH-001",
                type="forbid_pattern",
                pattern=r"from\s+infrastructure\b|import\s+infrastructure\b",
                scope=("src/domain/**",),
                severity="block",
                description="Domain must not import infrastructure implementations.",
            ),
            ConstraintV1(
                id="ARCH-002",
                type="forbid_pattern",
                pattern=r"from\s+services\b|import\s+services\b",
                scope=("src/domain/**",),
                severity="block",
                description="Domain must not import application/service orchestration code.",
            ),
        ]
        for index, requirement in enumerate(requirements.security_requirements, start=3):
            result.append(
                ConstraintV1(
                    id=f"ARCH-{index:03d}",
                    type="custom",
                    severity="block",
                    description=requirement.statement,
                    params={"requirement_id": requirement.id},
                )
            )
        return tuple(result)

    @staticmethod
    def _interface_contracts(requirements: RequirementsSpecification) -> tuple[str, ...]:
        result = []
        for req in requirements.integration_requirements:
            result.append(f"interface:{req.id}: {req.statement}")
        for req in requirements.functional_requirements:
            if any(word in req.statement.lower() for word in ("api", "endpoint", "interface")):
                result.append(f"interface:{req.id}: {req.statement}")
        return tuple(result)

    @staticmethod
    def _data_models(requirements: RequirementsSpecification) -> tuple[str, ...]:
        return tuple(f"data-model:{req.id}: {req.statement}" for req in requirements.data_requirements)

    @staticmethod
    def _technology_constraints(requirements: RequirementsSpecification) -> tuple[str, ...]:
        return tuple(req.statement for req in requirements.constraints)

    def _dilemmas(self, requirements: RequirementsSpecification) -> list[Decision]:
        text = self._text(requirements)
        decisions: list[Decision] = []
        if self._contains_any(text, ("sql", "postgres", "relational", "nosql", "document database")) and self._contains_any(
            text, ("nosql", "document database", "relational", "postgres", "sql")
        ):
            decisions.append(self._database_decision(requirements))
        if self._contains_any(text, ("sync", "synchronous", "async", "asynchronous", "event driven", "event-driven")):
            decisions.append(self._async_decision(requirements))
        return decisions

    @staticmethod
    def _database_decision(requirements: RequirementsSpecification) -> Decision:
        return Decision(
            project_id=str(requirements.project.get("id") or requirements.specification_id),
            category=DecisionCategory.ARCHITECTURE,
            question="Which persistence model should the architecture adopt: relational SQL or NoSQL/document storage?",
            alternatives=[
                DecisionAlternative(
                    key="A", title="Relational SQL", description="Use a relational database such as PostgreSQL.",
                    pros=["Strong consistency and constraints", "Mature transactional tooling"],
                    cons=["Less flexible schema evolution for highly variable documents"], risks=["Potential scaling complexity for extreme write volume"],
                    risk_level=RiskLevel.MEDIUM,
                ),
                DecisionAlternative(
                    key="B", title="NoSQL/document", description="Use a document-oriented persistence model.",
                    pros=["Flexible document shape", "Convenient horizontal scaling for selected workloads"],
                    cons=["Weaker relational guarantees", "More application-level consistency"], risks=["Data integrity and query complexity"],
                    risk_level=RiskLevel.HIGH,
                ),
            ],
            provenance_id=requirements.fingerprint,
            risk_level=RiskLevel.HIGH,
        )

    @staticmethod
    def _async_decision(requirements: RequirementsSpecification) -> Decision:
        return Decision(
            project_id=str(requirements.project.get("id") or requirements.specification_id),
            category=DecisionCategory.ARCHITECTURE,
            question="Should the integration flow be synchronous request/response or asynchronous/event-driven?",
            alternatives=[
                DecisionAlternative(
                    key="A", title="Synchronous", description="Use direct request/response calls.",
                    pros=["Simple control flow", "Immediate error propagation"], cons=["Tighter temporal coupling"], risks=["Latency and availability coupling"],
                    risk_level=RiskLevel.MEDIUM,
                ),
                DecisionAlternative(
                    key="B", title="Asynchronous", description="Use queues/events for decoupled processing.",
                    pros=["Loose coupling", "Better resilience for long-running work"], cons=["More operational complexity", "Eventual consistency"], risks=["Delivery/replay/idempotency complexity"],
                    risk_level=RiskLevel.HIGH,
                ),
            ],
            provenance_id=requirements.fingerprint,
            risk_level=RiskLevel.HIGH,
        )

    @staticmethod
    def _related_requirement_ids(requirements: RequirementsSpecification, question: str) -> tuple[str, ...]:
        terms = set(re.findall(r"[a-zA-Z]{4,}", question.lower()))
        return tuple(
            req.id
            for req in requirements.all_items()
            if isinstance(req, Requirement) and terms.intersection(set(re.findall(r"[a-zA-Z]{4,}", req.statement.lower())))
        )

    @staticmethod
    def _text(requirements: RequirementsSpecification) -> str:
        items: Iterable[object] = requirements.all_items()
        return " ".join(getattr(item, "statement", getattr(item, "question", "")) for item in items).lower()

    @staticmethod
    def _contains_any(text: str, terms: Iterable[str]) -> bool:
        return any(term in text for term in terms)
