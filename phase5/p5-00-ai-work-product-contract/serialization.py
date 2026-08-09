"""Canonical serialization for P5-00 contracts and submissions."""

from __future__ import annotations

from dataclasses import asdict, is_dataclass
from typing import Any

from .fingerprinting import canonical_json

SCHEMA_VERSION = "p5-00.v1"


def canonical_bytes(value: Any) -> bytes:
    """Serialize a P5-00 object/value into canonical UTF-8 JSON bytes."""
    if not is_dataclass(value):
        raise TypeError("P5-00 serialization expects a dataclass domain object")
    return canonical_json({"schema_version": SCHEMA_VERSION, "value": asdict(value)})


def canonical_fingerprint(value: Any) -> str:
    """Return the canonical fingerprint including the P5-00 schema version."""
    from .fingerprinting import fingerprint
    if not is_dataclass(value):
        raise TypeError("P5-00 fingerprinting expects a dataclass domain object")
    return fingerprint({"schema_version": SCHEMA_VERSION, "value": asdict(value)})
