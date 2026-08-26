"""Registry for independently versioned security sentinels."""
from __future__ import annotations

from dataclasses import dataclass
from threading import RLock


@dataclass(frozen=True)
class Sentinel:
    """Immutable sentinel registration metadata."""
    sentinel_id: str
    version: str
    weight: int = 1
    veto: bool = False

    def __post_init__(self) -> None:
        if not self.sentinel_id or not self.version:
            raise ValueError("sentinel_id and version are required")
        if self.weight < 1:
            raise ValueError("weight must be positive")


class SentinelRegistry:
    """Thread-safe registry of security voting authorities."""

    def __init__(self) -> None:
        self._lock = RLock()
        self._sentinels: dict[str, Sentinel] = {}

    def register(self, sentinel_id: str, version: str, weight: int = 1, veto: bool = False) -> Sentinel:
        """Register or replace a sentinel identity."""
        sentinel = Sentinel(sentinel_id, version, weight, veto)
        with self._lock:
            if sentinel_id in self._sentinels:
                raise ValueError(f"sentinel already registered: {sentinel_id}")
            self._sentinels[sentinel_id] = sentinel
        return sentinel

    def unregister(self, sentinel_id: str) -> None:
        """Remove a sentinel registration."""
        with self._lock:
            self._sentinels.pop(sentinel_id, None)

    def get(self, sentinel_id: str) -> Sentinel:
        """Return a registered sentinel or raise KeyError."""
        with self._lock:
            return self._sentinels[sentinel_id]

    def all(self) -> tuple[Sentinel, ...]:
        """Return a stable snapshot of all registrations."""
        with self._lock:
            return tuple(self._sentinels.values())
