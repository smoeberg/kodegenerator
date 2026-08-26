"""Resource and rate limiter governor for autonomous swarm workers."""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Dict, Optional, Set


@dataclass
class TokenBucket:
    capacity: float
    refill_rate: float  # tokens per second
    tokens: float = field(init=False)
    last_refill: float = field(init=False)

    def __post_init__(self) -> None:
        self.tokens = float(self.capacity)
        self.last_refill = time.monotonic()

    def consume(self, amount: float = 1.0) -> bool:
        now = time.monotonic()
        elapsed = now - self.last_refill
        self.last_refill = now
        self.tokens = min(self.capacity, self.tokens + elapsed * self.refill_rate)
        if self.tokens >= amount:
            self.tokens -= amount
            return True
        return False


class ResourceGovernor:
    """Manages token rate-limits and file concurrency locking for swarm tasks."""

    def __init__(
        self,
        default_capacity: float = 60.0,
        default_refill_rate: float = 1.0,
    ) -> None:
        self._default_capacity = default_capacity
        self._default_refill_rate = default_refill_rate
        self._buckets: Dict[str, TokenBucket] = {}
        self._active_file_locks: Set[str] = set()
        self._lock = threading.Lock()
        self._tokens_consumed: Dict[str, float] = {}

    def get_or_create_bucket(self, capability: str) -> TokenBucket:
        with self._lock:
            if capability not in self._buckets:
                self._buckets[capability] = TokenBucket(
                    capacity=self._default_capacity,
                    refill_rate=self._default_refill_rate,
                )
            return self._buckets[capability]

    def acquire_budget(self, capability: str, estimated_tokens: float = 1.0) -> bool:
        bucket = self.get_or_create_bucket(capability)
        with self._lock:
            granted = bucket.consume(estimated_tokens)
            if granted:
                self._tokens_consumed[capability] = (
                    self._tokens_consumed.get(capability, 0.0) + estimated_tokens
                )
            return granted

    def acquire_file_lock(self, file_path: str) -> bool:
        with self._lock:
            if file_path in self._active_file_locks:
                return False
            self._active_file_locks.add(file_path)
            return True

    def release_file_lock(self, file_path: str) -> None:
        with self._lock:
            self._active_file_locks.discard(file_path)

    def total_consumed(self, capability: Optional[str] = None) -> float:
        with self._lock:
            if capability:
                return self._tokens_consumed.get(capability, 0.0)
            return sum(self._tokens_consumed.values())
