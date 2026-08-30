"""Tests for the Phase 4 evidence enforcer (100% AC-coverage gate)."""

import pytest

from phase4.contracts.models import Evidence, KnowledgeRecord
from phase4.verification import (
    EvidenceEnforcementStatus,
    EvidenceEnforcer,
)


def make_record(evidence: tuple[Evidence, ...]) -> KnowledgeRecord:
    return KnowledgeRecord(
        record_id="rec-ev",
        subject="generated app",
        claim="all ACs met",
        evidence=evidence,
        author_agent_id="agent-ev",
    )


E1 = Evidence(
    evidence_id="e1",
    source="tests/test_login.py",
    content_digest="abc",
    supports=True,
    acceptance_criterion="AC-1",
)
E2 = Evidence(
    evidence_id="e2",
    source="tests/test_login.py",
    content_digest="def",
    supports=True,
    acceptance_criterion="AC-2",
)


def test_enforcer_accepts_full_coverage():
    result = EvidenceEnforcer().enforce(
        make_record((E1, E2)),
        criteria=["AC-1", "AC-2"],
    )
    assert result.status is EvidenceEnforcementStatus.ACCEPTED
    assert result.accepted
    assert result.coverage == 1.0
    assert result.total_criteria == 2
    assert result.covered_criteria == 2
    assert result.missing_criteria == ()


def test_enforcer_rejects_missing_criterion():
    result = EvidenceEnforcer().enforce(
        make_record((E1,)),
        criteria=["AC-1", "AC-2"],
    )
    assert result.status is EvidenceEnforcementStatus.REJECTED
    assert not result.accepted
    assert result.coverage == 0.5
    assert result.missing_criteria == ("AC-2",)


def test_enforcer_rejects_contradicting_evidence():
    contradicted = Evidence(
        evidence_id="e2",
        source="tests/test_login.py",
        content_digest="def",
        supports=False,
        acceptance_criterion="AC-2",
    )
    result = EvidenceEnforcer().enforce(
        make_record((E1, contradicted)),
        criteria=["AC-1", "AC-2"],
    )
    assert result.status is EvidenceEnforcementStatus.REJECTED
    assert result.coverage == 0.5
    assert result.missing_criteria == ("AC-2",)


def test_enforcer_accepts_mapping_candidate():
    result = EvidenceEnforcer().enforce(
        {
            "candidate_id": "map-cand",
            "evidence": [
                {
                    "evidence_id": "e1",
                    "source": "tests/test_a.py",
                    "content_digest": "a",
                    "supports": True,
                    "acceptance_criterion": "AC-1",
                }
            ],
        },
        criteria=["AC-1"],
    )
    assert result.accepted
    assert result.coverage == 1.0


def test_enforcer_rejects_empty_evidence_when_criteria_declared():
    result = EvidenceEnforcer().enforce(
        make_record(()),
        criteria=["AC-1"],
    )
    assert result.status is EvidenceEnforcementStatus.REJECTED
    assert result.coverage == 0.0
    assert result.missing_criteria == ("AC-1",)


def test_enforcer_infers_criteria_from_evidence():
    result = EvidenceEnforcer().enforce(make_record((E1, E2)))
    assert result.accepted
    assert result.total_criteria == 2


def test_enforcer_fingerprint_is_bounded_and_immutable():
    result = EvidenceEnforcer().enforce(
        make_record((E1, E2)),
        criteria=["AC-1", "AC-2"],
    )
    assert len(result.fingerprint) == 64
    with pytest.raises((AttributeError, TypeError)):
        result.coverage = 0.0
