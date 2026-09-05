"""Immutable contracts for declaring why an external repository is onboarded.

The contract is intentionally captured before repository audit. Purpose is a
closed enum, target-stack intent is explicit, and corrections create a new
record linked to the previous intent rather than mutating history.

This module does not authorize or persist declarations. The canonical command
boundary will derive ``declared_by``, ``organization_id`` and ``declared_at``
from trusted server context when it records an :class:`OnboardingIntent`.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import StrEnum
from typing import Any

from generation.project_spec import ProjectDefinition


_FINGERPRINT_RE = re.compile(r"^[0-9a-f]{64}$")
_AUTHORITY_GLOB_CHARS = frozenset("*?[")


class OnboardingContractError(ValueError):
    """Raised when onboarding intent cannot be represented canonically."""


class OnboardingPurpose(StrEnum):
    """Closed set of human-declared purposes for repository onboarding."""

    EXTEND = "extend"
    MODERNIZE_REWRITE = "modernize_rewrite"
    AUDIT_ONLY = "audit_only"


@dataclass(frozen=True)
class OnboardingIntentDraft:
    """Human-supplied semantic intent before trusted identity is attached.

    ``declared_by``, organization ownership and declaration time deliberately do
    not belong here. A client can propose the semantic intent, but it cannot
    claim who authenticated the declaration or which organization owns it.
    """

    source_repository: str
    purpose: OnboardingPurpose
    rationale: str
    target_stack: ProjectDefinition | None = None
    supersedes_intent_id: str | None = None

    def __post_init__(self) -> None:
        _canonical_text(self.source_repository, "source_repository")
        _canonical_text(self.rationale, "rationale")
        if any(
            character in self.source_repository
            for character in _AUTHORITY_GLOB_CHARS
        ):
            raise OnboardingContractError(
                "source_repository must be an exact identity without authority glob characters"
            )
        if not isinstance(self.purpose, OnboardingPurpose):
            raise OnboardingContractError(
                "purpose must be a declared OnboardingPurpose"
            )
        if self.target_stack is not None and not isinstance(
            self.target_stack, ProjectDefinition
        ):
            raise OnboardingContractError(
                "target_stack must be a ProjectDefinition when supplied"
            )

        has_target = self.target_stack is not None
        if self.purpose is OnboardingPurpose.MODERNIZE_REWRITE and not has_target:
            raise OnboardingContractError(
                "MODERNIZE_REWRITE requires an explicit target_stack"
            )
        if self.purpose is not OnboardingPurpose.MODERNIZE_REWRITE and has_target:
            raise OnboardingContractError(
                "target_stack is only allowed for MODERNIZE_REWRITE"
            )
        if self.supersedes_intent_id is not None:
            _fingerprint_id(self.supersedes_intent_id, "supersedes_intent_id")

    @property
    def content_fingerprint(self) -> str:
        """Fingerprint only the human-declared semantic content."""

        return _fingerprint(self.semantic_payload())

    def semantic_payload(self) -> dict[str, Any]:
        """Return stable semantic content used by audit/downstream binding.

        Supersession is provenance about how a record relates to history, not a
        change to the meaning of the declared purpose. It is therefore excluded
        from this payload and bound separately into the recorded ``intent_id``.
        """

        return {
            "source_repository": self.source_repository,
            "purpose": self.purpose.value,
            "rationale": self.rationale,
            "target_stack": _target_stack_payload(self.target_stack),
        }


@dataclass(frozen=True)
class OnboardingIntent:
    """Recorded onboarding intent with trusted actor and organization binding.

    ``intent_id`` is deterministic for the exact semantic declaration, actor,
    organization and supersession edge. ``declared_at`` is provenance metadata
    and is intentionally excluded from identity so command retries do not create
    new logical intents merely because wall-clock time changed.
    """

    source_repository: str
    purpose: OnboardingPurpose
    rationale: str
    declared_by: str
    organization_id: str
    target_stack: ProjectDefinition | None = None
    supersedes_intent_id: str | None = None
    declared_at: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    intent_id: str = field(init=False)
    content_fingerprint: str = field(init=False)

    def __post_init__(self) -> None:
        draft = OnboardingIntentDraft(
            source_repository=self.source_repository,
            purpose=self.purpose,
            rationale=self.rationale,
            target_stack=self.target_stack,
            supersedes_intent_id=self.supersedes_intent_id,
        )
        _canonical_text(self.declared_by, "declared_by")
        _canonical_text(self.organization_id, "organization_id")
        declared_at = _utc_datetime(self.declared_at, "declared_at")
        object.__setattr__(self, "declared_at", declared_at)
        object.__setattr__(self, "content_fingerprint", draft.content_fingerprint)

        identity_payload = {
            **draft.semantic_payload(),
            "declared_by": self.declared_by,
            "organization_id": self.organization_id,
            "supersedes_intent_id": self.supersedes_intent_id,
        }
        object.__setattr__(self, "intent_id", _fingerprint(identity_payload))

        if self.supersedes_intent_id == self.intent_id:
            raise OnboardingContractError(
                "an onboarding intent cannot supersede itself"
            )

    @classmethod
    def from_draft(
        cls,
        draft: OnboardingIntentDraft,
        *,
        declared_by: str,
        organization_id: str,
        declared_at: datetime | None = None,
    ) -> "OnboardingIntent":
        """Attach trusted server-owned declaration metadata to a validated draft."""

        if not isinstance(draft, OnboardingIntentDraft):
            raise TypeError("draft must be an OnboardingIntentDraft")
        return cls(
            source_repository=draft.source_repository,
            purpose=draft.purpose,
            rationale=draft.rationale,
            declared_by=declared_by,
            organization_id=organization_id,
            target_stack=draft.target_stack,
            supersedes_intent_id=draft.supersedes_intent_id,
            declared_at=declared_at or datetime.now(timezone.utc),
        )

    def canonical(self) -> dict[str, Any]:
        """Return a stable, JSON-ready provenance representation."""

        return {
            "intent_id": self.intent_id,
            "content_fingerprint": self.content_fingerprint,
            "source_repository": self.source_repository,
            "purpose": self.purpose.value,
            "rationale": self.rationale,
            "declared_by": self.declared_by,
            "organization_id": self.organization_id,
            "target_stack": _target_stack_payload(self.target_stack),
            "supersedes_intent_id": self.supersedes_intent_id,
            "declared_at": self.declared_at.isoformat(),
        }


def _target_stack_payload(
    target_stack: ProjectDefinition | None,
) -> dict[str, Any] | None:
    if target_stack is None:
        return None
    return target_stack.model_dump(mode="json")


def _fingerprint(payload: object) -> str:
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _canonical_text(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise OnboardingContractError(
            f"{field_name} must be a non-empty string"
        )
    if value != value.strip():
        raise OnboardingContractError(
            f"{field_name} must not contain outer whitespace"
        )
    return value


def _fingerprint_id(value: object, field_name: str) -> str:
    canonical = _canonical_text(value, field_name)
    if not _FINGERPRINT_RE.fullmatch(canonical):
        raise OnboardingContractError(
            f"{field_name} must be a lowercase SHA-256 fingerprint"
        )
    return canonical


def _utc_datetime(value: object, field_name: str) -> datetime:
    if not isinstance(value, datetime):
        raise OnboardingContractError(f"{field_name} must be a datetime")
    if value.tzinfo is None or value.utcoffset() is None:
        raise OnboardingContractError(
            f"{field_name} must be timezone-aware"
        )
    return value.astimezone(timezone.utc)
