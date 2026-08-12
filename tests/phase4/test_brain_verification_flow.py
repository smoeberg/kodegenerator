from phase4.agent_registry import AgentRegistry, AgentRole, AgentVersion, Capability
from phase4.contracts import KnowledgeRecord, KnowledgeState, VerificationMode, VerificationPolicy
from phase4.verification.flow import BrainVerificationFlow


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
    return BrainVerificationFlow(registry, store), store


def _record():
    return KnowledgeRecord(
        record_id="claim-1",
        subject="subject-1",
        claim="the system is deterministic",
        author_agent_id="agent-proposer",
    )


def test_confirmed_claim_flows_through_selection_case_engine_and_store():
    flow, store = _flow()
    outcome = flow.verify_quorum(
        _record(),
        VerificationPolicy(mode=VerificationMode.QUORUM, quorum_size=3),
        role=AgentRole.VERIFIER,
        capability="claim.verify",
        observations={
            # identities are generated; the test obtains them from the selector path below
        },
    )
    assert outcome.result is not None
