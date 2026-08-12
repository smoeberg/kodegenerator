from phase4.agent_registry import AgentRegistry, AgentRole, AgentVersion, Capability
from phase4.contracts import KnowledgeRecord, KnowledgeState, VerificationMode, VerificationPolicy
from phase4.verification.flow import BrainVerificationFlow
from phase4.verification.selector import VerifierSelector


class FakeKnowledgeStore:
    def __init__(self):
        self.records = []

    def append_and_materialize(self, record):
        self.records.append(record)
        return record.version + 1


def _flow():
    registry = AgentRegistry()
    for number in range(3):
        registry.register(
            agent_type=f"verifier-{number}",
            version=AgentVersion(1, 0, 0),
            role=AgentRole.VERIFIER,
            capabilities=(Capability.create("claim.verify", AgentVersion(1, 0, 0)),),
        )
    store = FakeKnowledgeStore()
    return registry, BrainVerificationFlow(registry, store), store


def _record():
    return KnowledgeRecord(
        record_id="claim-1",
        subject="subject-1",
        claim="the system is deterministic",
        author_agent_id="agent-proposer",
    )


def _selected(registry):
    selection = VerifierSelector(registry).select(
        claim_id="claim-1",
        policy_id="verification:quorum:3:0",
        quorum_size=3,
        role=AgentRole.VERIFIER,
        capability="claim.verify",
    )
    return selection.selected_ids


def test_confirmed_claim_flows_through_selection_case_engine_and_store():
    registry, flow, store = _flow()
    selected = _selected(registry)
    outcome = flow.verify_quorum(
        _record(),
        VerificationPolicy(mode=VerificationMode.QUORUM, quorum_size=3),
        role=AgentRole.VERIFIER,
        capability="claim.verify",
        observations={agent_id: True for agent_id in selected},
    )
    assert outcome.result.value == "confirmed"
    assert outcome.record.state is KnowledgeState.CONFIRMED
    assert outcome.selected_agent_ids == selected
    assert outcome.materialized_version == 1
    assert outcome.record.version == outcome.materialized_version
    assert store.records[0].state is KnowledgeState.CONFIRMED


def test_disagreement_is_materialized_as_disputed():
    registry, flow, store = _flow()
    selected = _selected(registry)
    observations = {selected[0]: True, selected[1]: False, selected[2]: True}
    outcome = flow.verify_quorum(
        _record(),
        VerificationPolicy(mode=VerificationMode.QUORUM, quorum_size=3),
        role=AgentRole.VERIFIER,
        capability="claim.verify",
        observations=observations,
    )
    assert outcome.result.value == "escalate"
    assert outcome.materialized_version is None
    assert store.records == []


def test_partial_quorum_does_not_materialize():
    registry, flow, store = _flow()
    selected = _selected(registry)
    outcome = flow.verify_quorum(
        _record(),
        VerificationPolicy(mode=VerificationMode.QUORUM, quorum_size=3),
        role=AgentRole.VERIFIER,
        capability="claim.verify",
        observations={selected[0]: True, selected[1]: True},
    )
    assert outcome.result.value == "insufficient"
    assert outcome.materialized_version is None
    assert store.records == []
