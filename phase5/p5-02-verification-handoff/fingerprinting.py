"""Canonical fingerprints for deterministic verification handoff identity."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, is_dataclass
from enum import Enum


def _normalize(value):
    if is_dataclass(value):
        return _normalize(asdict(value))
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, dict):
        return {str(k): _normalize(v) for k, v in sorted(value.items(), key=lambda x: str(x[0]))}
    if isinstance(value, (tuple, list)):
        return [_normalize(v) for v in value]
    return value


def canonical_bytes(value) -> bytes:
    return json.dumps(_normalize(value), sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")


def fingerprint(value) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()
