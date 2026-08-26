"""Cryptographically signed multi-sentinel consensus for patch approval."""
from __future__ import annotations

import hashlib
import hmac
from dataclasses import dataclass
from enum import Enum
from threading import RLock
from typing import Optional

from .sentinel_registry import SentinelRegistry


class Verdict(str, Enum):
    """Allowed sentinel verdicts."""
    APPROVE = "APPROVE"
    REJECT = "REJECT"
    ABSTAIN = "ABSTAIN"


class ConsensusStatus(str, Enum):
    """Aggregate consensus states."""
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    PENDING = "PENDING"


@dataclass(frozen=True)
class Vote:
    """Signed, immutable sentinel vote bound to a patch hash."""
    patch_hash: str
    verdict: Verdict
    sentinel_id: str
    signature: str


@dataclass(frozen=True)
class ConsensusResult:
    """Auditable aggregate voting result."""
    status: ConsensusStatus
    approvals: int
    rejections: int
    abstentions: int
    vetoed: bool
    votes: tuple[Vote, ...]


class ConsensusVoting:
    """Collect and evaluate independent sentinel votes with configurable quorum."""

    def __init__(self, registry: SentinelRegistry, required: int, total: int) -> None:
        if required < 1 or total < required:
            raise ValueError("quorum must satisfy 1 <= required <= total")
        self.registry = registry
        self.required = required
        self.total = total
        self._lock = RLock()
        self._votes: dict[str, dict[str, Vote]] = {}
        self._secrets: dict[str, bytes] = {}

    @staticmethod
    def patch_hash(patch: str) -> str:
        """Return the canonical SHA-256 digest of a patch."""
        return hashlib.sha256(patch.encode("utf-8")).hexdigest()

    def register_signing_secret(self, sentinel_id: str, secret: bytes) -> None:
        """Set the local signing secret for a registered sentinel."""
        self.registry.get(sentinel_id)
        if not secret:
            raise ValueError("secret must not be empty")
        with self._lock:
            self._secrets[sentinel_id] = bytes(secret)

    def sign_vote(self, patch_hash: str, verdict: Verdict, sentinel_id: str) -> Vote:
        """Create a deterministic HMAC-SHA256 signature over vote material."""
        sentinel = self.registry.get(sentinel_id)
        with self._lock:
            secret = self._secrets.get(sentinel_id)
        if secret is None:
            raise ValueError(f"no signing secret for sentinel: {sentinel_id}")
        message = f"{patch_hash}:{verdict.value}:{sentinel.sentinel_id}".encode("utf-8")
        signature = hmac.new(secret, message, hashlib.sha256).hexdigest()
        return Vote(patch_hash, verdict, sentinel_id, signature)

    def add_vote(self, vote: Vote) -> ConsensusResult:
        """Verify and record one vote, rejecting duplicates or forged signatures."""
        sentinel = self.registry.get(vote.sentinel_id)
        with self._lock:
            secret = self._secrets.get(vote.sentinel_id)
            if secret is None:
                raise ValueError("unknown signing secret")
            message = f"{vote.patch_hash}:{vote.verdict.value}:{sentinel.sentinel_id}".encode("utf-8")
            expected = hmac.new(secret, message, hashlib.sha256).hexdigest()
            if not hmac.compare_digest(expected, vote.signature):
                raise ValueError("invalid vote signature")
            bucket = self._votes.setdefault(vote.patch_hash, {})
            if vote.sentinel_id in bucket:
                raise ValueError("duplicate vote")
            bucket[vote.sentinel_id] = vote
            return self._evaluate(vote.patch_hash)

    def evaluate(self, patch_hash: str) -> ConsensusResult:
        """Evaluate the current votes for a patch hash."""
        with self._lock:
            return self._evaluate(patch_hash)

    def _evaluate(self, patch_hash: str) -> ConsensusResult:
        votes = tuple(self._votes.get(patch_hash, {}).values())
        vetoed = any(v.verdict is Verdict.REJECT and self.registry.get(v.sentinel_id).veto for v in votes)
        approvals = sum(1 for v in votes if v.verdict is Verdict.APPROVE)
        rejections = sum(1 for v in votes if v.verdict is Verdict.REJECT)
        abstentions = sum(1 for v in votes if v.verdict is Verdict.ABSTAIN)
        decisive = approvals + rejections
        if vetoed or rejections >= self.required:
            status = ConsensusStatus.REJECTED
        elif approvals >= self.required:
            status = ConsensusStatus.APPROVED
        elif decisive >= self.total:
            status = ConsensusStatus.REJECTED
        else:
            status = ConsensusStatus.PENDING
        return ConsensusResult(status, approvals, rejections, abstentions, vetoed, votes)
