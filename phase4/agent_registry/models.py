"""Domain models for DOR AI-1 Agent Registry.

The registry owns stable agent-instance identity and declarations. It does not
authorize actions or own worker execution state.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from enum import Enum
from typing import Any


class AgentRole(str, Enum):
    VERIFIER = "verifier"
    COMPILER = "compiler"
    DISTRIBUTOR = "distributor"
    ORCHESTRATOR = "orchestrator"
    EXECUTOR = "executor"
    CONTEXT_PROVIDER = "context_provider"
    AUDITOR = "auditor"
    OTHER = "other"


@dataclass(frozen=True, order=True)
class AgentVersion:
    major: int
    minor: int
    patch: int

    def __post_init__(self) -> None:
        if min(self.major, self.minor, self.patch) < 0:
            raise ValueError("version components must be non-negative")

    @classmethod
    def parse(cls, value: str) -> AgentVersion:
        parts = value.split(".")
        if len(parts) != 3 or not all(p.isdigit() for p in parts):
            raise ValueError(f"invalid semantic version: {value!r}")
        return cls(*(int(p) for p in parts))

    def __str__(self) -> str:
        return f"{self.major}.{self.minor}.{self.patch}"


@dataclass(frozen=True)
class Capability:
    """A declared capability. Declaration is not authorization."""

    name: str
    version: AgentVersion
    parameters: tuple[tuple[str, Any], ...] = ()

    @classmethod
    def create(
        cls,
        name: str,
        version: AgentVersion,
        parameters: Mapping[str, Any] | None = None,
    ) -> Capability:
        if not name or not name.strip():
            raise ValueError("capability name must be non-empty")
        params = tuple(sorted((parameters or {}).items(), key=lambda item: item[0]))
        return cls(name=name, version=version, parameters=params)

    def canonical(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "version": str(self.version),
            "parameters": {k: v for k, v in self.parameters},
        }


@dataclass(frozen=True)
class AgentIdentity:
    """Stable content identity for one agent instance declaration."""

    value: str

    @classmethod
    def derive(
        cls,
        agent_type: str,
        version: AgentVersion,
        role: AgentRole,
        capabilities: tuple[Capability, ...],
        trust_anchor: str | None = None,
        instance_id: str = "default",
    ) -> AgentIdentity:
        if not isinstance(instance_id, str) or not instance_id.strip():
            raise ValueError("instance_id must be a non-empty string")
        canonical = {
            "agent_type": agent_type,
            "instance_id": instance_id,
            "version": str(version),
            "role": role.value,
            "capabilities": [
                c.canonical()
                for c in sorted(
                    capabilities, key=lambda c: (c.name, str(c.version), c.parameters)
                )
            ],
            "trust_anchor": trust_anchor,
        }
        encoded = json.dumps(
            canonical, sort_keys=True, separators=(",", ":"), ensure_ascii=False
        ).encode()
        return cls(hashlib.sha256(encoded).hexdigest())

    def __str__(self) -> str:
        return self.value


@dataclass(frozen=True)
class AgentRecord:
    """Immutable registered agent instance declaration plus metadata.

    Worker/lease state intentionally does not belong here; it is assignment
    and execution state owned by the runtime queue.
    """

    identity: AgentIdentity
    agent_type: str
    instance_id: str
    version: AgentVersion
    role: AgentRole
    capabilities: tuple[Capability, ...]
    trust_anchor: str | None = None
    registered_by: str = "system"
    registered_at: str = ""
    active: bool = True

    def has_capability(self, name: str) -> bool:
        return any(cap.name == name for cap in self.capabilities)
