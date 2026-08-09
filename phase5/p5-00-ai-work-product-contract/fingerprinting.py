"""Canonical JSON and SHA-256 fingerprints for P5-00 domain objects."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, is_dataclass
from datetime import date, datetime, timezone
from enum import Enum
from typing import Any


def _normalize(value: Any) -> Any:
    if is_dataclass(value):
        return _normalize(asdict(value))
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, datetime):
        value = value.astimezone(timezone.utc) if value.tzinfo else value.replace(tzinfo=timezone.utc)
        return value.isoformat().replace("+00:00", "Z")
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(k): _normalize(v) for k, v in sorted(value.items(), key=lambda item: str(item[0]))}
    if isinstance(value, (list, tuple)):
        return [_normalize(v) for v in value]
    if isinstance(value, (set, frozenset)):
        return sorted((_normalize(v) for v in value), key=lambda v: json.dumps(v, sort_keys=True, separators=(",", ":")))
    return value


def canonical_json(value: Any) -> bytes:
    """Return deterministic UTF-8 JSON bytes for a supported value."""
    return json.dumps(
        _normalize(value),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")


def fingerprint(value: Any) -> str:
    """Return the SHA-256 hex fingerprint of canonical representation."""
    return hashlib.sha256(canonical_json(value)).hexdigest()
