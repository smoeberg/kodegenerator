"""Immutable domain models for AI-2 Context Packet Engine."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Optional, Tuple
import hashlib
import json


Scalar = str | int | float | bool | None


def _freeze(value: Any) -> Any:
    """Convert supported JSON-like values to a deterministic immutable shape."""
    if isinstance(value, Mapping):
        return tuple(sorted((str(k), _freeze(v)) for k, v in value.items()))
    if isinstance(value, (list, tuple)):
        return tuple(_freeze(v) for v in value)
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    raise TypeError(f"unsupported context value type: {type(value).__name__}")


def _thaw(value: Any) -> Any:
    if isinstance(value, tuple):
        if all(isinstance(x, tuple) and len(x) == 2 and isinstance(x[0], str) for x in value):
            return {k: _thaw(v) for k, v in value}
        return [_thaw(v) for v in value]
    return value


@dataclass(frozen=True)
class ContextItem:
    """A single piece of context with explicit provenance and relevance."""

    source: str
    key: str
    value: Any
    relevance: float = 1.0
    provenance: str = ""
    sensitivity: str = "normal"

    def __post_init__(self) -> None:
        if not self.source.strip() or not self.key.strip():
            raise ValueError("context source and key must be non-empty")
        if not 0.0 <= self.relevance <= 1.0:
            raise ValueError("relevance must be between 0 and 1")
        if self.sensitivity not in {"public", "normal", "sensitive"}:
            raise ValueError("unsupported sensitivity classification")
        object.__setattr__(self, "value", _freeze(self.value))

    def canonical(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "key": self.key,
            "value": _thaw(self.value),
            "relevance": self.relevance,
            "provenance": self.provenance,
            "sensitivity": self.sensitivity,
        }


@dataclass(frozen=True)
class ContextRequest:
    """Declarative request for context; it contains no authorization decision."""

    agent_identity: str
    purpose: str
    requested_keys: Tuple[str, ...] = ()
    max_items: int = 50
    max_bytes: int = 64 * 1024
    allowed_sensitivity: Tuple[str, ...] = ("public", "normal")

    def __post_init__(self) -> None:
        if not self.agent_identity.strip():
            raise ValueError("agent_identity must be non-empty")
        if not self.purpose.strip():
            raise ValueError("purpose must be non-empty")
        if self.max_items < 1:
            raise ValueError("max_items must be positive")
        if self.max_bytes < 1:
            raise ValueError("max_bytes must be positive")
        if any(s not in {"public", "normal", "sensitive"} for s in self.allowed_sensitivity):
            raise ValueError("unsupported sensitivity classification")


@dataclass(frozen=True)
class ContextPacket:
    """Deterministic, bounded snapshot handed to a downstream agent."""

    packet_id: str
    agent_identity: str
    purpose: str
    items: Tuple[ContextItem, ...]
    created_at: str
    truncated: bool = False

    @staticmethod
    def derive_id(
        agent_identity: str,
        purpose: str,
        items: Tuple[ContextItem, ...],
    ) -> str:
        payload = {
            "agent_identity": agent_identity,
            "purpose": purpose,
            "items": [item.canonical() for item in items],
        }
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
        return hashlib.sha256(encoded).hexdigest()

    def canonical(self) -> dict[str, Any]:
        return {
            "packet_id": self.packet_id,
            "agent_identity": self.agent_identity,
            "purpose": self.purpose,
            "items": [item.canonical() for item in self.items],
            "created_at": self.created_at,
            "truncated": self.truncated,
        }
