"""Tests for multi-sentinel consensus voting."""
from __future__ import annotations

import pytest

from services.consensus_voting import ConsensusStatus, ConsensusVoting, Verdict
from services.sentinel_registry import SentinelRegistry


def setup_consensus(required: int = 2, total: int = 3) -> ConsensusVoting:
    registry = SentinelRegistry()
    for index in range(total):
        registry.register(f"s{index}", "1.0", veto=index == 0)
    voting = ConsensusVoting(registry, required, total)
    for index in range(total):
        voting.register_signing_secret(f"s{index}", f"secret-{index}".encode())
    return voting


def test_two_of_three_approves():
    voting = setup_consensus()
    patch = voting.patch_hash("diff")
    for sentinel in ("s0", "s1"):
        result = voting.add_vote(voting.sign_vote(patch, Verdict.APPROVE, sentinel))
    assert result.status is ConsensusStatus.APPROVED
    assert result.abstentions == 0


def test_veto_rejects_even_when_quorum_approves():
    voting = setup_consensus()
    patch = voting.patch_hash("diff")
    voting.add_vote(voting.sign_vote(patch, Verdict.APPROVE, "s1"))
    result = voting.add_vote(voting.sign_vote(patch, Verdict.REJECT, "s0"))
    assert result.status is ConsensusStatus.REJECTED
    assert result.vetoed is True


def test_forged_signature_is_rejected():
    voting = setup_consensus()
    patch = voting.patch_hash("diff")
    vote = voting.sign_vote(patch, Verdict.APPROVE, "s1")
    forged = type(vote)(vote.patch_hash, vote.verdict, vote.sentinel_id, "00" * 32)
    with pytest.raises(ValueError, match="invalid vote signature"):
        voting.add_vote(forged)


def test_abstentions_do_not_count_toward_quorum():
    voting = setup_consensus()
    patch = voting.patch_hash("diff")
    voting.add_vote(voting.sign_vote(patch, Verdict.ABSTAIN, "s0"))
    result = voting.add_vote(voting.sign_vote(patch, Verdict.APPROVE, "s1"))
    assert result.status is ConsensusStatus.PENDING
    assert result.abstentions == 1


def test_duplicate_votes_are_rejected():
    voting = setup_consensus()
    patch = voting.patch_hash("diff")
    vote = voting.sign_vote(patch, Verdict.APPROVE, "s1")
    voting.add_vote(vote)
    with pytest.raises(ValueError, match="duplicate vote"):
        voting.add_vote(vote)
