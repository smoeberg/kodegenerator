"""Tests for deterministic architecture synthesis."""
from domain.architecture_contract_v1 import ArchitectureContractV1
from domain.decision import Decision, DecisionCategory, RiskLevel
from domain.requirements import (
    AcceptanceCriterion,
    Requirement,
    RequirementsSpecification,
    approval_for,
)
from services.architecture_dependency_evaluator import ImportEdge, evaluate_dependency_rules
from services.architecture_synthesis import ArchitectureSynthesisEngine


def make_requirements(*, approved: bool = True) -> RequirementsSpecification:
    draft = RequirementsSpecification(
        schema_version="1.0",
        specification_id="REQ-checkout",
        project={"name": "checkout-service", "id": "checkout"},
        version="1.0.0",
        status="review" if not approved else "draft",
        intent={"goal": "Process orders through a secure API"},
        functional_requirements=(Requirement("FR-001", "Expose an API endpoint to create orders", "human"),),
        non_functional_requirements=(Requirement("NFR-001", "The API must be auditable", "human"),),
        data_requirements=(Requirement("DR-001", "Persist orders with transactional integrity", "human"),),
        integration_requirements=(Requirement("IR-001", "Integrate with a payment API", "human"),),
        constraints=(Requirement("CON-001", "Prefer SQL or NoSQL depending on workload", "human"),),
        acceptance_criteria=(AcceptanceCriterion("AC-001", "An order can be created", requirement_ids=("FR-001",)),),
    )
    if not approved:
        return draft
    app = approval_for(draft, "controller-1")
    return RequirementsSpecification(
        schema_version=draft.schema_version,
        specification_id=draft.specification_id,
        project=draft.project,
        version=draft.version,
        status="approved",
        intent=draft.intent,
        functional_requirements=draft.functional_requirements,
        non_functional_requirements=draft.non_functional_requirements,
        data_requirements=draft.data_requirements,
        integration_requirements=draft.integration_requirements,
        constraints=draft.constraints,
        acceptance_criteria=draft.acceptance_criteria,
        approval=app,
    )


def test_synthesis_generates_machine_evaluable_contract():
    result = ArchitectureSynthesisEngine().synthesize(make_requirements())
    assert result.contract is not None
    assert result.contract.project_name == "checkout-service"
    assert result.contract.version == "1.0.0"
    assert len(result.contract.layers) >= 4
    assert result.contract.status == "review"


def test_synthesis_exposes_interface_and_data_model_contracts():
    result = ArchitectureSynthesisEngine().synthesize(make_requirements())
    assert len(result.interface_contracts) >= 1
    assert any("order" in item.lower() for item in result.data_models)


def test_synthesis_formulates_architecture_decision_for_database_dilemma():
    requirements = make_requirements()
    result = ArchitectureSynthesisEngine().synthesize(requirements)
    assert result.decisions
    decision = result.decisions[0]
    assert isinstance(decision, Decision)
    assert decision.category == DecisionCategory.ARCHITECTURE
    assert decision.risk_level == RiskLevel.HIGH
    assert len(decision.alternatives) == 2
    assert any("SQL" in alt.title for alt in decision.alternatives)
    assert any("NoSQL" in alt.title for alt in decision.alternatives)


def test_generated_contract_passes_ast_dependency_validation():
    result = ArchitectureSynthesisEngine().synthesize(make_requirements())
    edges = (
        ImportEdge("src/adapters/checkout.py", "src/application/checkout.py"),
        ImportEdge("src/application/checkout.py", "src/domain/checkout.py"),
        ImportEdge("src/infrastructure/checkout.py", "src/domain/checkout.py"),
    )
    eval_result = evaluate_dependency_rules(result.contract, edges)
    assert eval_result.status == "PASS"


def test_contract_round_trip_preserves_synthesis():
    result = ArchitectureSynthesisEngine().synthesize(make_requirements())
    payload = result.contract.to_dict()
    reconstructed = ArchitectureContractV1.from_dict(payload)
    assert reconstructed.project_name == result.contract.project_name
    assert reconstructed.layers == result.contract.layers
    assert reconstructed.dependency_rules == result.contract.dependency_rules
    assert reconstructed.constraints == result.contract.constraints
