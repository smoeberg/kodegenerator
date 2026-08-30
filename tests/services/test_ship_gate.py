"""Tests for the fail-closed ShipGate service."""
from unittest.mock import MagicMock

import pytest

from phase4.authority.grants import VerifiedAuthorityGrant
from phase4.contracts import Evidence, KnowledgeRecord, KnowledgeState
from phase6.execution import AuditHarness, ExecutionAuditEvent
from phase6.execution.audit import utc_timestamp
from services.github_pr_contracts import PatchInfo, PRMetadata, PRResult, PRStatus
from services.ship_gate import ShipGate, ShipGateError


class _FakePublisher:
    def __init__(self):
        self.calls = 0

    @property
    def repo_full_name(self) -> str:
        return "owner/repo"

    def publish_patch_as_pr(self, **kwargs) -> PRResult:
        self.calls += 1
        return PRResult(status=PRStatus.CREATED, pr_number=1, pr_url="https://x")


def make_record(state: KnowledgeState = KnowledgeState.CONFIRMED) -> KnowledgeRecord:
    return KnowledgeRecord(
        record_id="record-1",
        subject="s",
        claim="c",
        evidence=(Evidence(evidence_id="e1", source="src", content_digest="d", supports=True),),
        author_agent_id="a1",
        state=state,
    )


def make_grant(patch_id: str = "patch-1") -> VerifiedAuthorityGrant:
    grant = MagicMock(spec=VerifiedAuthorityGrant)
    grant.verified = True
    grant.action = "release.publish"
    grant.resource = "repository:owner/repo"
    grant.parameters = ((("patch_id", patch_id), ("base_branch", "main")))
    return grant


def make_patch() -> PatchInfo:
    return PatchInfo(patch_content="diff --git a/x b/x", patch_id="patch-1", author="a1")


def make_tests() -> dict:
    return {"status": "passed", "total": 3, "failed": 0, "passed": 3}


def make_harness() -> AuditHarness:
    harness = AuditHarness(chain_id="release-1")
    harness.append(ExecutionAuditEvent(
        event_type="verify", execution_id="exec-1", adapter_id="judge",
        outcome="confirmed", timestamp=utc_timestamp(),
    ))
    return harness


def test_ship_gate_allows_complete_evidence():
    gate = ShipGate(_FakePublisher())
    decision = gate.evaluate(
        patch=make_patch(),
        record=make_record(),
        grant=make_grant(),
        test_results=make_tests(),
        audit_harness=make_harness(),
    )
    assert decision.allowed


def test_ship_gate_requires_confirmed_record():
    gate = ShipGate(_FakePublisher())
    decision = gate.evaluate(
        patch=make_patch(),
        record=make_record(KnowledgeState.PROPOSED),
        grant=make_grant(),
        test_results=make_tests(),
        audit_harness=make_harness(),
    )
    assert not decision.allowed
    assert "CONFIRMED" in decision.reason


def test_ship_gate_rejects_ungranted_patch():
    gate = ShipGate(_FakePublisher())
    decision = gate.evaluate(
        patch=make_patch(),
        record=make_record(),
        grant=make_grant(patch_id="other-patch"),
        test_results=make_tests(),
        audit_harness=make_harness(),
    )
    assert not decision.allowed
    assert "patch" in decision.reason


def test_ship_gate_fails_closed_on_bad_tests_or_missing_audit():
    gate = ShipGate(_FakePublisher())
    assert not gate.evaluate(
        patch=make_patch(), record=make_record(), grant=make_grant(),
        test_results={"status": "failed"}, audit_harness=make_harness(),
    ).allowed
    assert not gate.evaluate(
        patch=make_patch(), record=make_record(), grant=make_grant(),
        test_results=make_tests(), audit_harness=None,
    ).allowed


def test_ship_gate_ship_publishes_only_when_allowed():
    publisher = _FakePublisher()
    gate = ShipGate(publisher)
    result = gate.ship(
        patch=make_patch(),
        pr_metadata=PRMetadata(title="T", description="D", branch="b", base_branch="main"),
        record=make_record(),
        grant=make_grant(),
        test_results=make_tests(),
        audit_harness=make_harness(),
        push_remote=False,
    )
    assert result.status is PRStatus.CREATED
    assert publisher.calls == 1


def test_ship_gate_ship_raises_on_rejection_without_publishing():
    publisher = _FakePublisher()
    gate = ShipGate(publisher)
    with pytest.raises(ShipGateError):
        gate.ship(
            patch=make_patch(),
            pr_metadata=PRMetadata(title="T", description="D", branch="b", base_branch="main"),
            record=make_record(KnowledgeState.PROPOSED),
            grant=make_grant(),
            test_results=make_tests(),
            audit_harness=make_harness(),
            push_remote=False,
        )
    assert publisher.calls == 0
