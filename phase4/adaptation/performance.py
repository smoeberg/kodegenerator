"""Append-only empirical bot performance facts and reproducible snapshots."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _digest(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


@dataclass(frozen=True)
class PerformanceObservation:
    organization_id: str
    observation_id: str
    bot_profile_id: str
    role_id: str
    task_context: str
    event_type: str
    value: float
    model_id: str
    prompt_version: str
    rubric_id: str
    evidence: tuple[str, ...]
    source: str
    ledger_position: int
    supersedes_observation_id: str | None = None
    event_time: datetime = field(default_factory=_now)

    def __post_init__(self) -> None:
        if self.ledger_position < 1 or not self.evidence:
            raise ValueError(
                "observation requires evidence and a positive ledger position"
            )
        if self.event_time.tzinfo is None or self.event_time.utcoffset() is None:
            raise ValueError("event_time must be timezone-aware")
        if self.observation_id != self.fingerprint:
            raise ValueError("observation_id must equal the content fingerprint")

    @property
    def fingerprint(self) -> str:
        return _digest(
            {
                key: value
                for key, value in self.__dict__.items()
                if key not in {"observation_id", "event_time"}
            }
        )

    @classmethod
    def create(cls, **values: Any) -> PerformanceObservation:
        identity = {
            **{key: value for key, value in values.items() if key != "event_time"},
            "supersedes_observation_id": values.get("supersedes_observation_id"),
        }
        return cls(observation_id=_digest(identity), **values)


@dataclass(frozen=True)
class PerformanceSnapshot:
    organization_id: str
    snapshot_id: str
    bot_profile_id: str
    role_id: str
    task_context: str
    sample_count: int
    window_start: datetime
    window_end: datetime
    definitions: tuple[tuple[str, str], ...]
    values: tuple[tuple[str, float], ...]
    confidence: float
    decay_version: str
    exclusions: tuple[str, ...]
    ledger_position: int
    created_at: datetime = field(default_factory=_now)

    def __post_init__(self) -> None:
        if (
            self.sample_count < 1
            or self.ledger_position < 1
            or not 0 <= self.confidence <= 1
        ):
            raise ValueError(
                "snapshot sample, ledger position, or confidence is invalid"
            )
        if self.window_start.tzinfo is None or self.window_end.tzinfo is None:
            raise ValueError("snapshot window must be timezone-aware")
        if self.snapshot_id != self.fingerprint:
            raise ValueError("snapshot_id must equal the content fingerprint")

    @property
    def fingerprint(self) -> str:
        return _digest(
            {
                key: value.isoformat() if isinstance(value, datetime) else value
                for key, value in self.__dict__.items()
                if key not in {"snapshot_id", "created_at"}
            }
        )

    @classmethod
    def create(cls, **values: Any) -> PerformanceSnapshot:
        identity = {
            key: value.isoformat() if isinstance(value, datetime) else value
            for key, value in values.items()
            if key != "created_at"
        }
        return cls(snapshot_id=_digest(identity), **values)
