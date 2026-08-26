"""Self-healing governance for the DOR swarm.

Provides bounded exponential retry backoff, diagnostic DLQ handling,
capability-scoped circuit breakers, and worker quarantine.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
from threading import RLock
from typing import Callable, Optional
import traceback

class CircuitState(str, Enum):
    CLOSED = "CLOSED"
    OPEN = "OPEN"
    HALF_OPEN = "HALF_OPEN"

@dataclass(frozen=True)
class FailureRecord:
    task_id: str
    agent_id: str
    error: str
    stack_trace: str
    attempt: int
    recorded_at: datetime
    retry_at: datetime

@dataclass(frozen=True)
class DeadLetter:
    task_id: str
    agent_id: str
    error: str
    stack_trace: str
    failures: tuple[FailureRecord, ...]
    created_at: datetime

@dataclass
class CircuitBreaker:
    capability: str
    threshold: float = 0.5
    window_seconds: int = 300
    cooldown_seconds: int = 300
    state: CircuitState = CircuitState.CLOSED
    opened_at: Optional[datetime] = None
    _events: list[tuple[datetime, bool]] = field(default_factory=list)
    def record(self, now: datetime, success: bool) -> None:
        self._events.append((now, success)); self._prune(now)
        if self.state == CircuitState.HALF_OPEN:
            if success: self.state, self.opened_at = CircuitState.CLOSED, None
            else: self._open(now)
            return
        total = len(self._events); failures = sum(not ok for _, ok in self._events)
        if total and failures > 0 and failures / total >= self.threshold: self._open(now)
    def allow(self, now: datetime) -> bool:
        self._prune(now)
        if self.state == CircuitState.CLOSED: return True
        if self.state == CircuitState.OPEN and self.opened_at and now >= self.opened_at + timedelta(seconds=self.cooldown_seconds):
            self.state = CircuitState.HALF_OPEN; return True
        return self.state == CircuitState.HALF_OPEN
    def _open(self, now: datetime) -> None: self.state, self.opened_at = CircuitState.OPEN, now
    def _prune(self, now: datetime) -> None:
        cutoff = now - timedelta(seconds=self.window_seconds)
        self._events = [(ts, ok) for ts, ok in self._events if ts >= cutoff]

class DeadLetterQueue:
    def __init__(self): self._items: dict[str, DeadLetter] = {}
    def put(self, item: DeadLetter) -> None: self._items[item.task_id] = item
    def get(self, task_id: str) -> Optional[DeadLetter]: return self._items.get(task_id)
    def items(self) -> tuple[DeadLetter, ...]: return tuple(self._items.values())

class SelfHealingGovernor:
    def __init__(self, *, max_retries=3, base_backoff_seconds=1.0, max_backoff_seconds=300.0,
                 circuit_threshold=0.5, circuit_window_seconds=300, circuit_cooldown_seconds=300,
                 clock: Optional[Callable[[], datetime]] = None):
        if max_retries < 0 or base_backoff_seconds <= 0 or max_backoff_seconds <= 0: raise ValueError("invalid retry/backoff values")
        if not 0 < circuit_threshold <= 1: raise ValueError("circuit_threshold must be in (0, 1]")
        self.max_retries=max_retries; self.base_backoff_seconds=base_backoff_seconds; self.max_backoff_seconds=max_backoff_seconds
        self._clock=clock or (lambda: datetime.now(timezone.utc)); self._threshold=circuit_threshold; self._window=circuit_window_seconds; self._cooldown=circuit_cooldown_seconds
        self._lock=RLock(); self._failures={}; self._circuits={}; self._quarantined=set(); self.dlq=DeadLetterQueue()
    def record_failure(self, task_id: str, error: str, agent_id: str) -> FailureRecord:
        now=self._clock()
        with self._lock:
            history=self._failures.setdefault(task_id, []); attempt=len(history)+1
            delay=min(self.max_backoff_seconds, self.base_backoff_seconds*(2**(attempt-1)))
            stack=traceback.format_exc()
            if stack.strip() == "NoneType: None": stack=error
            record=FailureRecord(task_id, agent_id, error, stack, attempt, now, now+timedelta(seconds=delay)); history.append(record)
            if attempt > self.max_retries: self.dlq.put(DeadLetter(task_id, agent_id, error, stack, tuple(history), now))
            return record
    def record_outcome(self, capability: str, success: bool) -> CircuitState:
        with self._lock:
            breaker=self._circuits.setdefault(capability, CircuitBreaker(capability, self._threshold, self._window, self._cooldown)); breaker.record(self._clock(), success); return breaker.state
    def dispatch_allowed(self, capability: str) -> bool:
        with self._lock:
            breaker=self._circuits.get(capability); return True if breaker is None else breaker.allow(self._clock())
    def quarantine_worker(self, agent_id: str) -> None:
        if not agent_id.strip(): raise ValueError("agent_id is required")
        with self._lock: self._quarantined.add(agent_id)
    def release_worker(self, agent_id: str) -> None:
        with self._lock: self._quarantined.discard(agent_id)
    def is_quarantined(self, agent_id: str) -> bool:
        with self._lock: return agent_id in self._quarantined
    def retry_count(self, task_id: str) -> int:
        with self._lock: return len(self._failures.get(task_id, []))
    def get_circuit_state(self, capability: str) -> CircuitState:
        with self._lock:
            breaker=self._circuits.get(capability); return CircuitState.CLOSED if breaker is None else breaker.state
