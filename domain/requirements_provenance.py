# domain/requirements_provenance.py
"""Requirement-specification identity carried by every pipeline artifact.

Completion plan, step 1: every artifact carries the requirement ids and the
requirement-specification version it was derived from, so that a later
change can be traced through all links and nothing works on a superseded
version.

A ``RequirementsRef`` is an immutable reference to one exact revision of the
pipeline requirements:

* ``revision`` is a monotonically increasing counter per pipeline (1 at start,
  +1 for every accepted change);
* ``fingerprint`` is the SHA-256 of the canonical JSON of the spec, using the
  same encoding as ``RequirementsSpecification.fingerprint``;
* ``declared_version`` is the free-text ``version`` the author wrote in the
  spec; it is informational and never used for identity;
* ``requirement_ids`` are the ids declared in the spec, in spec order.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any


class RequirementsProvenanceError(ValueError):
    """Raised when a requirements reference cannot be derived or trusted."""


def requirements_fingerprint(spec: Mapping[str, Any]) -> str:
    """Return the content identity of a requirements spec.

    The encoding matches ``RequirementsSpecification.fingerprint`` so the two
    requirement formats share one identity convention.
    """
    if not isinstance(spec, Mapping):
        raise RequirementsProvenanceError("requirements spec must be a mapping")
    try:
        encoded = json.dumps(
            spec, sort_keys=True, separators=(",", ":"), ensure_ascii=True
        )
    except (TypeError, ValueError) as exc:
        raise RequirementsProvenanceError(
            f"requirements spec is not canonically serialisable: {exc}"
        ) from exc
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def requirement_ids(spec: Mapping[str, Any]) -> tuple[str, ...]:
    """Return the declared requirement ids, failing closed on duplicates."""
    items = spec.get("requirements")
    if not isinstance(items, list) or not items:
        raise RequirementsProvenanceError("requirements spec has no requirements")
    ids: list[str] = []
    for item in items:
        if not isinstance(item, Mapping):
            raise RequirementsProvenanceError("each requirement must be a mapping")
        req_id = item.get("id")
        if not isinstance(req_id, str) or not req_id.strip():
            raise RequirementsProvenanceError("each requirement must have an id")
        ids.append(req_id.strip())
    if len(set(ids)) != len(ids):
        raise RequirementsProvenanceError("requirement ids must be unique")
    return tuple(ids)


@dataclass(frozen=True)
class RequirementsRef:
    revision: int
    fingerprint: str
    declared_version: str
    requirement_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        if (
            not isinstance(self.revision, int)
            or isinstance(self.revision, bool)
            or self.revision < 1
        ):
            raise RequirementsProvenanceError("revision must be a positive integer")
        if not isinstance(self.fingerprint, str) or len(self.fingerprint) != 64:
            raise RequirementsProvenanceError(
                "fingerprint must be a SHA-256 hex digest"
            )
        if not self.requirement_ids:
            raise RequirementsProvenanceError("requirement_ids must not be empty")

    @classmethod
    def derive(cls, spec: Mapping[str, Any], revision: int) -> RequirementsRef:
        return cls(
            revision=revision,
            fingerprint=requirements_fingerprint(spec),
            declared_version=str(spec.get("version", "")),
            requirement_ids=requirement_ids(spec),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "revision": self.revision,
            "fingerprint": self.fingerprint,
            "declared_version": self.declared_version,
            "requirement_ids": list(self.requirement_ids),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> RequirementsRef:
        if not isinstance(data, Mapping):
            raise RequirementsProvenanceError(
                "requirements reference must be a mapping"
            )
        try:
            return cls(
                revision=data["revision"],
                fingerprint=data["fingerprint"],
                declared_version=str(data.get("declared_version", "")),
                requirement_ids=tuple(data["requirement_ids"]),
            )
        except (KeyError, TypeError) as exc:
            raise RequirementsProvenanceError(
                f"invalid requirements reference: {exc}"
            ) from exc

    def same_revision(self, other: RequirementsRef) -> bool:
        return self.revision == other.revision and self.fingerprint == other.fingerprint
