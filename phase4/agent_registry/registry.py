"""AI-1 Agent Registry contract implementation.

This module deliberately does not authorize capabilities. AI-3 owns authority.
"""
from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional

from .models import AgentIdentity, AgentRecord, AgentRole, AgentVersion, Capability


class RegistryError(Exception):
    """Base registry error."""


class DuplicateIdentityError(RegistryError):
    """An identical agent declaration is already registered."""


class AgentNotFoundError(RegistryError):
    """The requested identity is not registered."""


class RegistrationError(RegistryError):
    """Registration input is invalid."""


class AgentRegistry:
    """In-memory reference implementation of the AI-1 registry contract."""

    def __init__(self) -> None:
        self._records: Dict[str, AgentRecord] = {}
        self._audit: List[dict[str, Any]] = []

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()

    def register(
        self,
        *,
        agent_type: str,
        version: AgentVersion,
        role: AgentRole,
        capabilities: Iterable[Capability] = (),
        trust_anchor: Optional[str] = None,
        actor: str = "system",
    ) -> AgentRecord:
        if not isinstance(agent_type, str) or not agent_type.strip():
            raise RegistrationError("agent_type must be a non-empty string")
        if not isinstance(version, AgentVersion):
            raise RegistrationError("version must be AgentVersion")
        if not isinstance(role, AgentRole):
            raise RegistrationError("role must be AgentRole")
        if not actor or not isinstance(actor, str):
            raise RegistrationError("actor must be a non-empty string")

        caps = tuple(sorted(set(capabilities), key=lambda c: (c.name, str(c.version), c.parameters)))
        if any(not isinstance(cap, Capability) for cap in caps):
            raise RegistrationError("capabilities must contain Capability values")

        identity = AgentIdentity.derive(
            agent_type=agent_type,
            version=version,
            role=role,
            capabilities=caps,
            trust_anchor=trust_anchor,
        )
        key = str(identity)
        if key in self._records:
            raise DuplicateIdentityError(key)

        record = AgentRecord(
            identity=identity,
            agent_type=agent_type,
            version=version,
            role=role,
            capabilities=caps,
            trust_anchor=trust_anchor,
            registered_by=actor,
            registered_at=self._now(),
            active=True,
        )
        self._records[key] = record
        self._append_audit("registered", record, actor)
        return record

    def get(self, identity: AgentIdentity, *, include_inactive: bool = False) -> AgentRecord:
        record = self._records.get(str(identity))
        if record is None or (not include_inactive and not record.active):
            raise AgentNotFoundError(str(identity))
        return record

    def list(self, *, role: Optional[AgentRole] = None, capability: Optional[str] = None) -> list[AgentRecord]:
        records = [r for r in self._records.values() if r.active]
        if role is not None:
            records = [r for r in records if r.role == role]
        if capability is not None:
            records = [r for r in records if r.has_capability(capability)]
        return sorted(records, key=lambda r: str(r.identity))

    def deactivate(self, identity: AgentIdentity, *, actor: str, reason: str = "") -> AgentRecord:
        if not actor or not isinstance(actor, str):
            raise RegistrationError("actor must be a non-empty string")
        current = self.get(identity)
        updated = replace(current, active=False)
        self._records[str(identity)] = updated
        self._append_audit("deactivated", updated, actor, {"reason": reason})
        return updated

    def audit_trail(self, identity: Optional[AgentIdentity] = None) -> list[dict[str, Any]]:
        if identity is None:
            return [dict(entry) for entry in self._audit]
        key = str(identity)
        return [dict(entry) for entry in self._audit if entry["identity"] == key]

    def _append_audit(
        self,
        operation: str,
        record: AgentRecord,
        actor: str,
        details: Optional[dict[str, Any]] = None,
    ) -> None:
        self._audit.append(
            {
                "operation": operation,
                "identity": str(record.identity),
                "actor": actor,
                "timestamp": self._now(),
                "details": dict(details or {}),
            }
        )
