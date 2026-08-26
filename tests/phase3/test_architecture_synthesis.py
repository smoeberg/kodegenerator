"""Tests for deterministic architecture synthesis."""
from domain.architecture_contract import ArchitectureContract, ArchitectureDecision
from domain.architecture_contract_v1 import ArchitectureContractV1
from domain.requirements import (
    AcceptanceCriterion,
    Requirement,
    RequirementsSpecification,
    approval_for,
)
from services.architecture_dependency_evaluator import ImportEdge, evaluate_dependency_rules
from services.architecture_synthesis import ArchitectureSynthesisEngine
from services.contract_compiler import compile_contracts


def make_requirements(*, approved: bool = True) -> RequirementsSpecification:
    base = RequirementsSpecification(
        schema_version="1.0",
        specification_id="REQ-checkout",
        project={"name": "checkout-service", "id": "checkout"},
        version="1.0.0",
        status="review" if not approved else "approved",
        intent={"goal": "Process orders through a secure API"},
        functional_requirements=(Requirement("FR-001", "Expose an API endpoint to create orders", "human"),),
        non_functional_requirements=(Requirement("NFR-001", "The API must be auditable", "human"),),
        data_requirements=(Requirement("DR-001", "Persist orders with transactional integrity", "human"),),
        integration_requirements=(Requirement("IR-001", "Integrate with a payment API", "human"),),
        constraints=(Requirement("CON-001", "Prefer SQL or NoSQL depending on workload", "human"),),
        acceptance_criteria=(AcceptanceCriterion("AC-001", "An order can be created", requirement_ids=("FR-001",)),),
    )
    if not approved:
        return base
    return RequirementsSpecification(**{**base.__dict__, "approval": approval_for(base, "controller-1")})


def test_synthesis_generates_machine_evaluable_contract():
    result = ArchitectureSynthesisEngine().synthesize(make_requirements())
    contract = result.contract
    assert isinstance(contract, ArchitectureContractV1)
    assert contract.schema_version == "1.0"
    assert contract.status == "review"
    assert contract.style == "clean"
    assert {layer.id for layer in contract.layers} >= {"domain", "application", "ports", "adapters", "infrastructure", "tests"}
    assert contract.rule_for_source("domain").may_depend_on == ()
    assert any(c.id == "ARCH-001" for c in contract.constraints)
    assert contract.quality_gates
    assert contract.traceability


def test_synthesis_exposes_interface_and_data_model_contracts():
    result = ArchitectureSynthesisEngine().synthesize(make_requirements())
    assert "interface:IR-001: Integrate with a payment API" in result.interface_contracts
    assert "data-model:DR-001: Persist orders with transactional integrity" in result.data_models


def test_synthesis_formulates_architecture_decision_for_database_dilemma():
    requirements = make_requirements()
    result = ArchitectureSynthesisEngine().synthesize(requirements)
    assert result.decisions
    decision = result.decisions[0]
    assert decision.category.value == "ARCHITECTURE"
    assert len(decision.alternatives) == 2
    assert {alternative.key for alternative in decision.alternatives} == {"A", "B"}
    assert decision.provenance_id == requirements.fingerprint


def test_generated_contract_passes_ast_dependency_validation():
    result = ArchitectureSynthesisEngine().synthesize(make_requirements())
    evaluation = evaluate_dependency_rules(
        result.contract,
        [
            ImportEdge("src/application/service.py", "src/domain/order.py"),
            ImportEdge("src/adapters/payment.py", "src/application/service.py"),
            ImportEdge("src/infrastructure/db.py", "src/domain/order.py"),
        ],
    )
    assert evaluation.status == "PASS"
    assert evaluation.contract_fingerprint == result.contract.fingerprint


def test_generated_architecture_can_cross_existing_contract_compiler_boundary():
    """The v1 contract is lowered explicitly to the legacy compiler input."""
    requirements = make_requirements()
    v1 = ArchitectureSynthesisEngine().synthesize(requirements).contract
    legacy = ArchitectureContract(
        schema_version=v1.schema_version,
        contract_id=v1.contract_id,
        version=v1.version,
        status="review",
        style=v1.style,
        components=tuple(layer.id for layer in v1.layers),
        boundaries=tuple(rule.id for rule in v1.dependency_rules),
        decisions=tuple(ArchitectureDecision(d.id, d.decision, d.rationale, d.constraints) for d in v1.decisions),
        technology_constraints=v1.technology_constraints,
        forbidden_patterns=tuple(c.pattern for c in v1.constraints if c.pattern),
    ).approve("controller-1")
    compilation = compile_contracts(requirements, legacy)
    assert compilation.package.architecture_fingerprint == legacy.fingerprint
    assert compilation.package.contracts


def test_contract_round_trip_preserves_synthesis():
    result = ArchitectureSynthesisEngine().synthesize(make_requirements())
    restored = ArchitectureContractV1.from_dict(result.contract.to_dict())
    assert restored.fingerprint == result.contract.fingerprint
    assert restored.layers == result.contract.layers
    assert restored.dependency_rules == result.contract.dependency_rules
