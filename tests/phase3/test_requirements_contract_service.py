import pytest

from domain.requirements import OpenQuestion
from services.requirements_contract_service import RequirementsApprovalError, approve, reject
from tests.phase3.test_requirements_contract import make_spec


def test_review_spec_can_be_approved_only_after_validation():
    approved = approve(make_spec(), "soeren")
    assert approved.status == "approved"
    assert approved.approval.status == "approved"
    assert approved.approval.content_fingerprint == approved.fingerprint


def test_blocking_question_prevents_approval():
    spec = make_spec(open_questions=(OpenQuestion("Q-001", "Which region?", True, "soeren"),))
    with pytest.raises(RequirementsApprovalError, match="BLOCKING_QUESTION"):
        approve(spec, "soeren")


def test_only_review_specification_can_be_approved():
    with pytest.raises(RequirementsApprovalError, match="review"):
        approve(make_spec(status="draft"), "soeren")


def test_rejection_is_explicit_and_does_not_mutate_input():
    spec = make_spec()
    rejected = reject(spec)
    assert spec.status == "review"
    assert rejected.status == "rejected"
    assert rejected.approval.status == "rejected"
