from datetime import datetime, timedelta, timezone

import pytest

from phase4.verification import VerificationResult
from phase4.verification.case import VerificationCase, VerificationCaseStatus
from phase4.verification.selection import VerifierSelection


def _case(deadline_at=None):
    selection = VerifierSelection(
        claim_id="claim-1",
        policy_id="policy-1",
        candidate_ids=("agent-a", "agent-b", "agent-c"),
        selected_ids=("agent-a", "agent-b"),
        seed="seed",
        reason="test",
    )
    return VerificationCase("claim-1", "policy-1", selection, deadline_at=deadline_at)


def test_records_only_selected_agents():
    case = _case()
    case.record("agent-a", True)
    assert case.observations == {"agent-a": True}


def test_rejects_unselected_agent():
    with pytest.raises(ValueError, match="not assigned"):
        _case().record("agent-c", True)


def test_rejects_duplicate_observation():
    case = _case()
    case.record("agent-a", True)
    with pytest.raises(ValueError, match="already"):
        case.record("agent-a", True)


def test_confirmation_completes_case():
    case = _case()
    case.complete(VerificationResult.CONFIRMED)
    assert case.status is VerificationCaseStatus.COMPLETE
    assert case.result is VerificationResult.CONFIRMED


def test_escalation_sets_escalated_status():
    case = _case()
    case.complete(VerificationResult.ESCALATE)
    assert case.status is VerificationCaseStatus.ESCALATED


def test_expiry_is_terminal():
    case = _case()
    case.expire()
    assert case.status is VerificationCaseStatus.EXPIRED
    with pytest.raises(ValueError, match="not open"):
        case.record("agent-a", True)


def test_deadline_expires_case_before_observation_is_recorded():
    deadline = datetime.now(timezone.utc) - timedelta(seconds=1)
    case = _case(deadline)

    with pytest.raises(ValueError, match="deadline has expired"):
        case.record("agent-a", True)

    assert case.status is VerificationCaseStatus.EXPIRED
    assert case.observations == {}


def test_deadline_blocks_completion():
    deadline = datetime.now(timezone.utc) - timedelta(seconds=1)
    case = _case(deadline)

    with pytest.raises(ValueError, match="deadline has expired"):
        case.complete(VerificationResult.CONFIRMED)

    assert case.status is VerificationCaseStatus.EXPIRED
    assert case.result is None


def test_deadline_must_be_timezone_aware():
    with pytest.raises(ValueError, match="timezone-aware"):
        _case(datetime.now())


def test_future_deadline_keeps_case_open():
    deadline = datetime.now(timezone.utc) + timedelta(minutes=1)
    case = _case(deadline)
    case.record("agent-a", True)
    assert case.status is VerificationCaseStatus.OPEN
