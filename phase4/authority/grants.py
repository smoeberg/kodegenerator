"""Tamper-evident authority credentials for the Phase 4 execution boundary."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
import base64
import binascii
import hashlib
import hmac
import json
import os
import secrets
from typing import Any

from .models import AuthorityDecision

DEFAULT_GRANT_TTL_SECONDS = 300
_PROVENANCE_VERSION = "p4-authority-grant-v1"
_ISSUER_ID = "phase4.ai-3"


def _load_signing_key() -> bytes:
    encoded = os.environ.get("DOR_AUTHORITY_SIGNING_KEY")
    is_test_env = os.environ.get("DOR_ENV", "development").lower() == "test"
    
    if encoded is None:
        if is_test_env:
            return secrets.token_bytes(32)
        raise RuntimeError(
            "DOR_AUTHORITY_SIGNING_KEY must be configured in production. "
            "Set a URL-safe base64 key of at least 32 bytes."
        )
    
    padded = encoded + "=" * (-len(encoded) % 4)
    try:
        key = base64.b64decode(padded, altchars=b"-_", validate=True)
    except (binascii.Error, ValueError) as exc:
        raise RuntimeError("DOR_AUTHORITY_SIGNING_KEY must be URL-safe base64") from exc
    
    if len(key) < 32:
        raise RuntimeError(
            "DOR_AUTHORITY_SIGNING_KEY must decode to at least 32 bytes. "
            f"Got {len(key)} bytes."
        )
    return key


_SIGNING_KEY = _load_signing_key()


def _canonical_bytes(kind: str, payload: dict[str, object]) -> bytes:
    envelope = {"kind": kind, "payload": payload, "version": _PROVENANCE_VERSION}
    return json.dumps(envelope, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def _signature_for(kind: str, payload: dict[str, object]) -> str:
    return hmac.new(_SIGNING_KEY, _canonical_bytes(kind, payload), hashlib.sha256).hexdigest()


def _decision_payload(decision: AuthorityDecision) -> dict[str, object]:
    return {
        "request_id": decision.request_id,
        "decision": decision.decision.value,
        "agent_identity": decision.agent_identity,
        "action": decision.action,
        "resource": decision.resource,
        "context_packet_id": decision.context_packet_id,
        "policy_id": decision.policy_id,
        "policy_version": decision.policy_version,
        "matched_rule_ids": list(decision.matched_rule_ids),
        "reason": decision.reason,
        "evaluated_at": decision.evaluated_at,
        "parameters": [list(item) for item in decision.parameters],
        "organization_id": decision.organization_id,
        "actor_id": decision.actor_id,
        "capability": decision.capability,
    }


def _attach_decision_provenance(decision: AuthorityDecision) -> None:
    object.__setattr__(decision, "_provenance_issuer", _ISSUER_ID)
    object.__setattr__(decision, "_provenance_signature", _signature_for("authority-decision", _decision_payload(decision)))


def _decision_has_valid_provenance(decision: AuthorityDecision) -> bool:
    if not isinstance(decision, AuthorityDecision):
        return False
    if getattr(decision, "_provenance_issuer", "") != _ISSUER_ID:
        return False
    supplied = getattr(decision, "_provenance_signature", "")
    if not supplied:
        return False
    expected = _signature_for("authority-decision", _decision_payload(decision))
    return hmac.compare_digest(supplied, expected)


def _aware_utc(value: datetime | None = None) -> datetime:
    instant = value or datetime.now(timezone.utc)
    if instant.tzinfo is None or instant.utcoffset() is None:
        raise ValueError("authority timestamps must be timezone-aware")
    return instant.astimezone(timezone.utc)


def _parse_timestamp(value: str) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed.astimezone(timezone.utc)


@dataclass(frozen=True)
class VerifiedAuthorityGrant:
    request_id: str
    agent_identity: str
    action: str
    resource: str
    context_packet_id: str
    policy_id: str
    policy_version: str
    matched_rule_ids: tuple[str, ...]
    decision: str
    parameters: tuple[tuple[str, str], ...] = ()
    organization_id: str | None = None
    actor_id: str | None = None
    capability: str | None = None
    issuer_id: str = ""
    grant_id: str = ""
    issued_at: str = ""
    expires_at: str = ""
    _signature: str = field(default="", init=False, repr=False, compare=False)

    @classmethod
    def from_decision(cls, decision: AuthorityDecision, *, ttl_seconds: int = DEFAULT_GRANT_TTL_SECONDS, now: datetime | None = None) -> "VerifiedAuthorityGrant":
        if not _decision_has_valid_provenance(decision):
            raise ValueError("authority decision has no verified AI-3 provenance")
        if decision.decision.value != "allow":
            raise ValueError("authority decision is not ALLOW")
        if type(ttl_seconds) is not int or not 1 <= ttl_seconds <= DEFAULT_GRANT_TTL_SECONDS:
            raise ValueError(f"ttl_seconds must be between 1 and {DEFAULT_GRANT_TTL_SECONDS}")
        issued = _aware_utc(now)
        expires = issued + timedelta(seconds=ttl_seconds)
        grant = cls(
            request_id=decision.request_id,
            agent_identity=decision.agent_identity,
            action=decision.action,
            resource=decision.resource,
            context_packet_id=decision.context_packet_id,
            policy_id=decision.policy_id,
            policy_version=decision.policy_version,
            matched_rule_ids=decision.matched_rule_ids,
            decision=decision.decision.value,
            parameters=decision.parameters,
            organization_id=decision.organization_id,
            actor_id=decision.actor_id,
            capability=decision.capability,
            issuer_id=_ISSUER_ID,
            grant_id=secrets.token_hex(16),
            issued_at=issued.isoformat(),
            expires_at=expires.isoformat(),
        )
        object.__setattr__(grant, "_signature", _signature_for("authority-grant", grant._signed_payload()))
        return grant

    def _signed_payload(self) -> dict[str, object]:
        return {
            "request_id": self.request_id,
            "agent_identity": self.agent_identity,
            "action": self.action,
            "resource": self.resource,
            "context_packet_id": self.context_packet_id,
            "policy_id": self.policy_id,
            "policy_version": self.policy_version,
            "matched_rule_ids": list(self.matched_rule_ids),
            "decision": self.decision,
            "parameters": [list(item) for item in self.parameters],
            "organization_id": self.organization_id,
            "actor_id": self.actor_id,
            "capability": self.capability,
            "issuer_id": self.issuer_id,
            "grant_id": self.grant_id,
            "issued_at": self.issued_at,
            "expires_at": self.expires_at,
        }

    def verify(self, *, at: datetime | None = None) -> bool:
        if self.issuer_id != _ISSUER_ID or not self.grant_id or not self._signature:
            return False
        issued = _parse_timestamp(self.issued_at)
        expires = _parse_timestamp(self.expires_at)
        if issued is None or expires is None or expires <= issued:
            return False
        instant = _aware_utc(at)
        if instant < issued or instant >= expires:
            return False
        expected = _signature_for("authority-grant", self._signed_payload())
        return hmac.compare_digest(self._signature, expected)

    @property
    def verified(self) -> bool:
        return self.verify()

    def binds(self, request: Any, *, at: datetime | None = None) -> bool:
        return (
            self.verify(at=at)
            and self.request_id == request.request_id
            and self.agent_identity == request.agent_identity
            and self.action == request.action
            and self.resource == request.resource
            and self.context_packet_id == request.context_packet_id
            and self.parameters == tuple(request.parameters)
            and self.organization_id == getattr(request, "organization_id", None)
            and self.actor_id == getattr(request, "actor_id", None)
            and self.capability == getattr(request, "capability", None)
        )
