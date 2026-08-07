from datetime import datetime, timezone

import pytest

from domain.requirements import (
    AcceptanceCriterion,
    Assumption,
    OpenQuestion,
    Requirement,
    RequirementsSpecification,
    RequirementsValidationError,
    TraceLink,
    approval_for,
)
from services.requirements_validator import validate_requirements


def make_spec(**overrides):
    data = dict(
        schema_version="0.1",
        specification_id="req-001",
        project={"name": "Example"},
        version="1.0",
        status="review",
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
    data.update(overrides)
    return RequirementsSpecification(**data)


def test_valid_specification_passes():
    result = validate_requirements(make_spec())
    assert result.valid
    assert result.blocking == ()


def test_must_requirement_without_acceptance_is_blocked():
    spec = make_spec(
        functional_requirements=(
            Requirement(id="FR-001", statement="Do something", priority="must", source="human"),
        ),
        acceptance_criteria=(),
    )
    result = validate_requirements(spec)
    assert not result.valid
    assert any(i.code == "MUST_WITHOUT_ACCEPTANCE" for i in result.issues)


def test_blocking_question_prevents_approval():
    spec = make_spec(
        open_questions=(OpenQuestion("Q-001", "Which region?", True, "owner"),),
    )
    result = validate_requirements(spec)
    assert any(i.code == "BLOCKING_QUESTION" for i in result.issues)


def test_agent_proposal_cannot_be_confirmed_silently():
    spec = make_spec(
        functional_requirements=(
            Requirement(
                id="FR-001", statement="Suggested behavior", priority="must",
                source="agent_proposed", status="confirmed", acceptance_criteria=("AC-001",),
            ),
        ),
    )
    result = validate_requirements(spec)
    assert any(i.code == "UNAPPROVED_AGENT_REQUIREMENT" for i in result.issues)


def test_unknown_acceptance_reference_is_blocking():
    spec = make_spec(
        functional_requirements=(
            Requirement(id="FR-001", statement="Do it", priority="must", source="human", acceptance_criteria=("AC-999",)),
        ),
    )
    result = validate_requirements(spec)
    assert any(i.code == "UNKNOWN_ACCEPTANCE_CRITERION" for i in result.issues)


def test_ids_must_be_stable_and_canonical():
    with pytest.raises(RequirementsValidationError):
        Requirement(id="REQ-1", statement="bad id", source="human")


def test_duplicate_ids_are_rejected_across_sections():
    with pytest.raises(RequirementsValidationError):
        make_spec(
            business_rules=(
                Requirement(id="FR-001", statement="duplicate", source="human"),
            ),
        )


def test_fingerprint_is_deterministic():
    first = make_spec()
    second = make_spec()
    assert first.fingerprint == second.fingerprint
    assert len(first.fingerprint) == 64


def test_fingerprint_changes_when_contract_changes():
    first = make_spec()
    second = make_spec(project={"name": "Different"})
    assert first.fingerprint != second.fingerprint


def test_approval_binds_exact_version_and_fingerprint():
    spec = make_spec()
    approval = approval_for(spec, "soeren", datetime(2026, 8, 7, tzinfo=timezone.utc))
    approved = RequirementsSpecification(**{**spec.__dict__, "status": "approved", "approval": approval})
    result = validate_requirements(approved)
    assert result.valid
    assert approved.approval.content_fingerprint == spec.fingerprint


def test_approved_specification_requires_proof():
    with pytest.raises(RequirementsValidationError):
        make_spec(status="approved")


def test_trace_link_is_explicit_and_typed():
    link = TraceLink("FR-001", "ADR-001", "satisfied_by")
    assert link.source_id == "FR-001"
    assert link.relation == "satisfied_by"


def test_assumptions_are_explicitly_marked_for_confirmation():
    assumption = Assumption("ASM-001", "User has email", "agent_proposed", "high", True)
    assert assumption.requires_confirmation


def test_open_question_requires_owner():
    with pytest.raises(RequirementsValidationError):
        OpenQuestion("Q-001", "Who owns this?", True, "")
