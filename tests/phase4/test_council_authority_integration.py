"""Integration tests for Council, Epistemics, and AI-3 Authority engine."""

import pytest

from phase4.authority import (
    AuthorityEngine,
    AuthorityError,
    AuthorityPolicy,
    AuthorityRequest,
    AuthorityRule,
    CouncilDecisionAdapter,
    Decision,
    RiskLevel,
)
from phase4.council import DeliberationSession
from phase4.epistemics import Evidence, EvidenceType, Hypothesis, HypothesisStatus


@pytest.fixture
def allow_policy():
    rule = AuthorityRule(
        rule_id="allow-patch-apply",
        action="patch.apply",
        resource_pattern="repo/src/*",
        effect=Decision.ALLOW,
        priority=10,
    )
    return AuthorityPolicy(
        policy_id="policy-p4-dev",
        version="1.0.0",
        rules=(rule,),
    )


@pytest.fixture
def sample_hypothesis():
    return Hypothesis(
        task_id="task-auth-int-1",
        statement="Update connection pool timeout in repo/src/db.py to 30 seconds",
        confidence=0.7,
        status=HypothesisStatus.ACTIVE,
    )


@pytest.fixture
def authority_request():
    return AuthorityRequest.create(
        agent_identity="agent-implementation-1",
        action="patch.apply",
        resource="repo/src/db.py",
        context_packet_id="packet-xyz",
    )


def test_grant_issued_when_council_approved_and_evidence_verified(
    allow_policy, sample_hypothesis, authority_request
):
    """Test standard happy path: Council reaches consensus, evidence verified -> Grant issued."""
    # 1. Deliberation Session
    session = DeliberationSession(sample_hypothesis, max_rounds=3)
    ev = Evidence(
        hypothesis_id=sample_hypothesis.hypothesis_id,
        evidence_type=EvidenceType.SUPPORTING,
        weight=0.25,
        source="load_test_suite",
        description="Empirical benchmark proves 30s timeout mitigates dropouts",
    )
    session.hypothesis.supporting_evidence.append(ev)
    session.cast_vote("reviewer-1", approved=True)
    session.cast_vote("reviewer-2", approved=True)
    session.conclude_round()

    # 2. Council Adapter creates DecisionReadiness
    current_rev = "git-commit-abc1234"
    evidence_map = {ev.evidence_id: current_rev}
    readiness = CouncilDecisionAdapter.evaluate(
        session=session,
        current_revision=current_rev,
        risk_level=RiskLevel.LOW,
        evidence_revision_map=evidence_map,
    )

    assert readiness.is_decision_ready is True
    assert readiness.open_critical_disputes == 0
    assert readiness.evidence_verified is True

    # 3. Authority Engine issues grant
    engine = AuthorityEngine(allow_policy, max_allowed_risk=RiskLevel.MEDIUM)
    grant = engine.issue_grant(authority_request, readiness_report=readiness)

    assert grant is not None
    assert grant.verified is True
    assert grant.action == "patch.apply"


def test_grant_denied_when_open_critical_dispute_exists(
    allow_policy, sample_hypothesis, authority_request
):
    """Test fail-closed: Grant issuance must fail if an open dispute exists."""
    session = DeliberationSession(sample_hypothesis, max_rounds=3)
    session.raise_dispute(
        agent_id="skeptic-agent",
        reason="Timeout increase might mask thread exhaustion deadlock",
    )

    current_rev = "git-commit-abc1234"
    readiness = CouncilDecisionAdapter.evaluate(
        session=session,
        current_revision=current_rev,
        risk_level=RiskLevel.LOW,
    )

    assert readiness.open_critical_disputes == 1
    assert readiness.is_decision_ready is False

    engine = AuthorityEngine(allow_policy, max_allowed_risk=RiskLevel.HIGH)

    with pytest.raises(AuthorityError, match="unresolved critical disputes"):
        engine.issue_grant(authority_request, readiness_report=readiness)


def test_grant_denied_when_evidence_stale_or_unverified(
    allow_policy, sample_hypothesis, authority_request
):
    """Test fail-closed: Grant denied when evidence revision does not match current target revision."""
    session = DeliberationSession(sample_hypothesis, max_rounds=3)
    ev = Evidence(
        hypothesis_id=sample_hypothesis.hypothesis_id,
        evidence_type=EvidenceType.SUPPORTING,
        weight=0.2,
        source="benchmark",
        description="Passes on commit old-123",
    )
    session.hypothesis.supporting_evidence.append(ev)
    session.cast_vote("reviewer-1", approved=True)
    session.conclude_round()

    current_rev = "git-commit-new-456"
    stale_evidence_map = {ev.evidence_id: "git-commit-old-123"}  # Mismatch!

    readiness = CouncilDecisionAdapter.evaluate(
        session=session,
        current_revision=current_rev,
        risk_level=RiskLevel.LOW,
        evidence_revision_map=stale_evidence_map,
    )

    assert readiness.evidence_verified is False

    engine = AuthorityEngine(allow_policy, max_allowed_risk=RiskLevel.HIGH)
    with pytest.raises(AuthorityError, match="evidence failed verification"):
        engine.issue_grant(authority_request, readiness_report=readiness)


def test_grant_denied_when_risk_exceeds_policy_ceiling(
    allow_policy, sample_hypothesis, authority_request
):
    """Test fail-closed: Grant denied when Council assessed risk exceeds maximum allowed risk policy."""
    session = DeliberationSession(sample_hypothesis, max_rounds=3)
    session.cast_vote("reviewer-1", approved=True)
    session.conclude_round()

    current_rev = "git-commit-abc1234"
    readiness = CouncilDecisionAdapter.evaluate(
        session=session,
        current_revision=current_rev,
        risk_level=RiskLevel.CRITICAL,  # Critical risk
    )

    # Engine only allows up to MEDIUM risk
    engine = AuthorityEngine(allow_policy, max_allowed_risk=RiskLevel.MEDIUM)

    with pytest.raises(AuthorityError, match="exceeds policy threshold"):
        engine.issue_grant(authority_request, readiness_report=readiness)
