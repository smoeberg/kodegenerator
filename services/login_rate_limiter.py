"""Process-local login throttling for the bootstrap authentication surface.

The limiter deliberately runs before password hashing so repeated rejected
requests cannot consume unbounded PBKDF2 CPU. It applies independent limits to
peer IP, username, and their pair, with bounded exponential backoff.
"""

from __future__ import annotations

import math
import os
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Callable


@dataclass
class _Bucket:
    failures: deque[float] = field(default_factory=deque)
    blocked_until: float = 0.0


class LoginRateLimiter:
    """Bounded in-memory limiter for one API process."""

    def __init__(
        self,
        *,
        window_seconds: int = 60,
        ip_limit: int = 30,
        username_limit: int = 10,
        pair_limit: int = 5,
        base_backoff_seconds: int = 1,
        max_backoff_seconds: int = 60,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if min(window_seconds, ip_limit, username_limit, pair_limit) <= 0:
            raise ValueError("login rate-limit windows and limits must be positive")
        if min(base_backoff_seconds, max_backoff_seconds) <= 0:
            raise ValueError("login rate-limit backoff values must be positive")
        self.window_seconds = window_seconds
        self.ip_limit = ip_limit
        self.username_limit = username_limit
        self.pair_limit = pair_limit
        self.base_backoff_seconds = base_backoff_seconds
        self.max_backoff_seconds = max_backoff_seconds
        self._clock = clock
        self._buckets: dict[str, _Bucket] = {}
        self._lock = threading.Lock()

    @classmethod
    def from_environment(cls) -> "LoginRateLimiter":
        return cls(
            window_seconds=int(os.getenv("DOR_LOGIN_RATE_WINDOW_SECONDS", "60")),
            ip_limit=int(os.getenv("DOR_LOGIN_RATE_IP_LIMIT", "30")),
            username_limit=int(os.getenv("DOR_LOGIN_RATE_USERNAME_LIMIT", "10")),
            pair_limit=int(os.getenv("DOR_LOGIN_RATE_PAIR_LIMIT", "5")),
            base_backoff_seconds=int(os.getenv("DOR_LOGIN_RATE_BACKOFF_SECONDS", "1")),
            max_backoff_seconds=int(os.getenv("DOR_LOGIN_RATE_MAX_BACKOFF_SECONDS", "60")),
        )

    @staticmethod
    def _normalize_username(username: str) -> str:
        return username.strip().casefold()

    def _keys(self, peer_ip: str, username: str) -> tuple[tuple[str, int], ...]:
        normalized_ip = (peer_ip or "unknown").strip() or "unknown"
        normalized_user = self._normalize_username(username)
        return (
            (f"ip:{normalized_ip}", self.ip_limit),
            (f"username:{normalized_user}", self.username_limit),
            (f"pair:{normalized_ip}:{normalized_user}", self.pair_limit),
        )

    def _prune(self, bucket: _Bucket, now: float) -> None:
        cutoff = now - self.window_seconds
        while bucket.failures and bucket.failures[0] <= cutoff:
            bucket.failures.popleft()

    def retry_after(self, peer_ip: str, username: str) -> int:
        """Return seconds until another attempt is allowed, or zero."""
        now = self._clock()
        with self._lock:
            retry = 0.0
            for key, _limit in self._keys(peer_ip, username):
                bucket = self._buckets.get(key)
                if bucket is None:
                    continue
                self._prune(bucket, now)
                retry = max(retry, bucket.blocked_until - now)
            return max(0, math.ceil(retry))

    def record_failure(self, peer_ip: str, username: str) -> int:
        """Record a failed login and return any resulting retry delay."""
        now = self._clock()
        with self._lock:
            retry = 0.0
            for key, limit in self._keys(peer_ip, username):
                bucket = self._buckets.setdefault(key, _Bucket())
                self._prune(bucket, now)
                bucket.failures.append(now)
                if len(bucket.failures) >= limit:
                    excess = len(bucket.failures) - limit
                    delay = min(
                        self.max_backoff_seconds,
                        self.base_backoff_seconds * (2**excess),
                    )
                    bucket.blocked_until = max(bucket.blocked_until, now + delay)
                retry = max(retry, bucket.blocked_until - now)
            return max(0, math.ceil(retry))

    def record_success(self, peer_ip: str, username: str) -> None:
        """Clear identity-specific failures after a valid credential exchange.

        The IP bucket is intentionally retained so one source cannot evade its
        aggregate limit by eventually guessing one valid credential.
        """
        normalized_ip = (peer_ip or "unknown").strip() or "unknown"
        normalized_user = self._normalize_username(username)
        with self._lock:
            self._buckets.pop(f"username:{normalized_user}", None)
            self._buckets.pop(f"pair:{normalized_ip}:{normalized_user}", None)
