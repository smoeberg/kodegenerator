import pytest

from phase4.agent_registry import AgentRegistry, AgentRole, AgentVersion, Capability
from phase4.verification.selection import VerifierSelector


def _registry() -> AgentRegistry:
    registry = AgentRegistry()
    for number in range(5):
        registry.register(
            agent_type=f"security-{number}",
            version=AgentVersion(1, 0, 0),
            role=AgentRole.AUDITOR,
            capabilities=(Capability.create("security.verify", AgentVersion(1, 0, 0)),),
        )
    return registry


def test_selection_is_reproducible():
    selector = VerifierSelector(_registry())
    first = selector.select(
        claim_id="claim-1", policy_id="policy-1", quorum_size=3,
        role=AgentRole.AUDITOR, capability="security.verify",
    )
    second = selector.select(
        claim_id="claim-1", policy_id="policy-1", quorum_size=3,
        role=AgentRole.AUDITOR, capability="security.verify",
    )
    assert first == second
    assert len(first.selected_ids) == 3


def test_selection_records_full_candidate_set():
    result = VerifierSelector(_registry()).select(
        claim_id="claim-2", policy_id="policy-1", quorum_size=2,
        role=AgentRole.AUDITOR, capability="security.verify",
    )
    assert len(result.candidate_ids) == 5
    assert set(result.selected_ids).issubset(result.candidate_ids)


def test_selection_requires_enough_candidates():
    with pytest.raises(ValueError, match="insufficient"):
        VerifierSelector(_registry()).select(
            claim_id="claim-3", policy_id="policy-1", quorum_size=6,
            role=AgentRole.AUDITOR, capability="security.verify",
        )
