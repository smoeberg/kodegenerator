from phase4.contracts import VerificationMode, VerificationPolicy, KnowledgeState
from phase4.verification import VerificationEngine, VerificationResult
from phase4.verification.engine import result_to_state


def test_deterministic_confirmation():
    policy = VerificationPolicy(mode=VerificationMode.DETERMINISTIC)
    assert VerificationEngine().evaluate(policy, [True]) is VerificationResult.CONFIRMED


def test_deterministic_rejection():
    policy = VerificationPolicy(mode=VerificationMode.DETERMINISTIC)
    assert VerificationEngine().evaluate(policy, [False]) is VerificationResult.DISPUTED


def test_quorum_requires_full_quorum():
    policy = VerificationPolicy(mode=VerificationMode.QUORUM, quorum_size=3)
    assert VerificationEngine().evaluate(policy, [True, True]) is VerificationResult.INSUFFICIENT


def test_quorum_confirms_unanimous_votes():
    policy = VerificationPolicy(mode=VerificationMode.QUORUM, quorum_size=3)
    assert VerificationEngine().evaluate(policy, [True, True, True]) is VerificationResult.CONFIRMED


def test_quorum_escalates_split_votes():
    policy = VerificationPolicy(mode=VerificationMode.QUORUM, quorum_size=3)
    assert VerificationEngine().evaluate(policy, [True, False, True]) is VerificationResult.ESCALATE


def test_confirmation_maps_to_knowledge_state_without_authority():
    assert result_to_state(VerificationResult.CONFIRMED) is KnowledgeState.CONFIRMED
