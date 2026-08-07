from datetime import datetime, timezone
from dataclasses import replace

import pytest

from domain.architecture_contract import ArchitectureContract, ArchitectureDecision
from domain.requirements import AcceptanceCriterion, Requirement, RequirementsSpecification, approval_for
from services.contract_compiler import ContractCompilationError, compile_contracts


def make_requirements(status="review"):
    return RequirementsSpecification(
        schema_version="0.1",
        specification_id="req-001",
        project={"name": "Example"},
        version="1.0",
        status=status,
        intent={"problem_statement": "Need a service", "desired_outcome": "Working service"},
        functional_requirements=(
            Requirement(
                id="FR-001",
                statement="A user can create an account.",
                priority="must",
                source="human",
                acceptance_criteria=("AC-001",),
            ),
        ),
        acceptance_criteria=(
            AcceptanceCriterion(
                id="AC-001",
                statement="Given valid data, when submitted, then an account exists.",
                requirement_ids=("FR-001",),
            ),
        ),
    )


def make_approved_requirements():
    review = make_requirements()
    approval = approval_for(review, "soeren", datetime(2026, 8, 7, tzinfo=timezone.utc))
    return replace(review, status="approved", approval=approval)


def make_architecture(status="review"):
    return ArchitectureContract(
        schema_version="0.1",
        contract_id="arch-001",
        version="1.0",
        status=status,
        style="hexagonal",
        components=("api", "application", "domain", "infrastructure"),
        boundaries=("domain has no infrastructure imports",),
        decisions=(ArchitectureDecision("ADR-001", "Use ports and adapters", "Keep domain logic isolated"),),
        technology_constraints=("Python 3.12+",),
        forbidden_patterns=("domain-to-infrastructure imports",),
    )


def make_approved_architecture():
    return make_architecture().approve("soeren", datetime(2026, 8, 7, tzinfo=timezone.utc))


def test_compiler_requires_human_approved_requirements():
    with pytest.raises(ContractCompilationError, match="Requirements must be human-approved"):
        compile_contracts(make_requirements(), make_approved_architecture())


def test_compiler_requires_human_approved_architecture():
    with pytest.raises(ContractCompilationError, match="Architecture must be human-approved"):
        compile_contracts(make_approved_requirements(), make_architecture())


def test_compiler_blocks_invalid_approved_requirements():
    invalid_review = replace(
        make_requirements(),
        functional_requirements=(
            Requirement(
                id="FR-001",
                statement="Agent suggestion",
                priority="must",
                source="agent_proposed",
                status="confirmed",
                acceptance_criteria=("AC-001",),
            ),
        ),
    )
    approval = approval_for(invalid_review, "soeren")
    invalid_approved = replace(invalid_review, status="approved", approval=approval)
    with pytest.raises(ContractCompilationError, match="Requirements contract is not valid"):
        compile_contracts(invalid_approved, make_approved_architecture())


def test_compiler_emits_all_specialist_contracts():
    result = compile_contracts(make_approved_requirements(), make_approved_architecture())
    assert {c.role for c in result.package.contracts} == {
        "development", "test", "audit", "security", "documentation", "project_management", "distribution"
    }


def test_every_agent_binds_both_source_fingerprints():
    requirements = make_approved_requirements()
    architecture = make_approved_architecture()
    package = compile_contracts(requirements, architecture).package
    assert all(c.source_requirements_fingerprint == requirements.fingerprint for c in package.contracts)
    assert all(c.source_architecture_fingerprint == architecture.fingerprint for c in package.contracts)


def test_compilation_is_deterministic():
    first = compile_contracts(make_approved_requirements(), make_approved_architecture()).package
    second = compile_contracts(make_approved_requirements(), make_approved_architecture()).package
    assert first.fingerprint == second.fingerprint
    assert [c.system_prompt for c in first.contracts] == [c.system_prompt for c in second.contracts]


def test_agent_prompt_contains_contract_fingerprint_and_boundaries():
    package = compile_contracts(make_approved_requirements(), make_approved_architecture()).package
    development = next(c for c in package.contracts if c.role == "development")
    assert development.fingerprint in development.system_prompt
    assert "FORBIDDEN ACTIONS:" in development.system_prompt
    assert "changing architecture" in development.system_prompt


def test_agent_contracts_have_nonempty_forbidden_actions():
    package = compile_contracts(make_approved_requirements(), make_approved_architecture()).package
    assert all(contract.forbidden_actions for contract in package.contracts)


def test_package_fingerprint_changes_when_architecture_changes():
    requirements = make_approved_requirements()
    first = compile_contracts(requirements, make_approved_architecture()).package
    changed_architecture = replace(make_approved_architecture(), technology_constraints=("Python 3.13+",))
    second = compile_contracts(requirements, changed_architecture).package
    assert first.fingerprint != second.fingerprint


def test_package_fingerprint_changes_when_requirements_change():
    first_requirements = make_approved_requirements()
    changed_review = replace(first_requirements, intent={"problem_statement": "Different", "desired_outcome": "Working service"})
    changed_approval = approval_for(changed_review, "soeren")
    changed_requirements = replace(changed_review, approval=changed_approval)
    first = compile_contracts(first_requirements, make_approved_architecture()).package
    second = compile_contracts(changed_requirements, make_approved_architecture()).package
    assert first.fingerprint != second.fingerprint


def test_compiler_does_not_call_or_require_an_ai_provider():
    package = compile_contracts(make_approved_requirements(), make_approved_architecture()).package
    assert package.contracts
    assert all("llm" not in contract.system_prompt.lower() for contract in package.contracts)


def test_distribution_contract_is_bounded():
    package = compile_contracts(make_approved_requirements(), make_approved_architecture()).package
    distribution = next(c for c in package.contracts if c.role == "distribution")
    assert "rewriting prompts" in distribution.forbidden_actions
    assert "selected_agent_contract" in distribution.permitted_outputs


def test_approved_requirements_fingerprint_is_stable_across_status_transition():
    review = make_requirements()
    approval = approval_for(review, "soeren")
    approved = replace(review, status="approved", approval=approval)
    assert review.fingerprint == approved.fingerprint
    assert approved.approval.content_fingerprint == approved.fingerprint
