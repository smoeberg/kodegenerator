"""Tenant-owned bot configuration linked to canonical AI-1 identities."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from urllib.parse import urlsplit

_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_SHA256 = re.compile(r"^[a-f0-9]{64}$")
_DATA_BOUNDARIES = frozenset({"local", "organization", "eu", "global"})
_DEPLOYMENT_STATES = frozenset({"active", "degraded", "disabled"})


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _identifier(name: str, value: str) -> str:
    if not isinstance(value, str) or not _IDENTIFIER.fullmatch(value):
        raise ValueError(f"{name} must be a canonical identifier")
    return value


def _text(name: str, value: str) -> str:
    if not isinstance(value, str) or not value.strip() or value != value.strip():
        raise ValueError(f"{name} must be canonical non-empty text")
    return value


def _aware(name: str, value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware")
    return value.astimezone(timezone.utc)


def _ordered(name: str, values: tuple[str, ...]) -> tuple[str, ...]:
    if any(not isinstance(value, str) or not value.strip() for value in values):
        raise ValueError(f"{name} must contain non-empty strings")
    canonical = tuple(sorted(set(values)))
    if values != canonical:
        raise ValueError(f"{name} must be sorted and unique")
    return values


def _fingerprint(payload: dict) -> str:
    encoded = json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True)
class BotDataPolicy:
    """Data placement rules used by later allocation hard filters."""

    boundary: str = "global"
    allowed_regions: tuple[str, ...] = ()
    source_code_allowed: bool = True

    def __post_init__(self) -> None:
        if self.boundary not in _DATA_BOUNDARIES:
            raise ValueError("unsupported bot data boundary")
        _ordered("allowed_regions", self.allowed_regions)

    def canonical(self) -> dict:
        return {
            "boundary": self.boundary,
            "allowed_regions": list(self.allowed_regions),
            "source_code_allowed": self.source_code_allowed,
        }


@dataclass(frozen=True)
class BotBudgetPolicy:
    """Per-call ceilings; zero is a valid cost ceiling for local models."""

    max_cost_minor_units: int | None = None
    max_input_tokens: int = 32_000
    max_output_tokens: int = 4_096

    def __post_init__(self) -> None:
        if self.max_cost_minor_units is not None and self.max_cost_minor_units < 0:
            raise ValueError("max_cost_minor_units must be non-negative")
        if self.max_input_tokens < 1 or self.max_output_tokens < 1:
            raise ValueError("token limits must be positive")

    def canonical(self) -> dict:
        return {
            "max_cost_minor_units": self.max_cost_minor_units,
            "max_input_tokens": self.max_input_tokens,
            "max_output_tokens": self.max_output_tokens,
        }


@dataclass(frozen=True)
class ProviderConnection:
    """One immutable version of a tenant-owned provider account or endpoint."""

    connection_id: str
    organization_id: str
    brand: str
    adapter_type: str
    endpoint: str
    secret_reference: str
    region: str | None = None
    data_boundary: str = "global"
    concurrency_limit: int = 1
    enabled: bool = True
    version: int = 1
    created_at: datetime = field(default_factory=_now)
    updated_at: datetime = field(default_factory=_now)

    def __post_init__(self) -> None:
        _identifier("connection_id", self.connection_id)
        _identifier("organization_id", self.organization_id)
        _text("brand", self.brand)
        _identifier("adapter_type", self.adapter_type)
        _text("secret_reference", self.secret_reference)
        parsed = urlsplit(self.endpoint)
        if parsed.scheme.lower() not in {"http", "https"} or not parsed.netloc:
            raise ValueError("endpoint must be an absolute HTTP(S) URL")
        if parsed.username is not None or parsed.password is not None:
            raise ValueError("endpoint must not contain credentials")
        if self.region is not None:
            _text("region", self.region)
        if self.data_boundary not in _DATA_BOUNDARIES:
            raise ValueError("unsupported provider data boundary")
        if self.concurrency_limit < 1 or self.version < 1:
            raise ValueError("concurrency_limit and version must be positive")
        _aware("created_at", self.created_at)
        _aware("updated_at", self.updated_at)

    @property
    def fingerprint(self) -> str:
        return _fingerprint(
            {
                "connection_id": self.connection_id,
                "organization_id": self.organization_id,
                "brand": self.brand,
                "adapter_type": self.adapter_type,
                "endpoint": self.endpoint,
                "secret_reference": self.secret_reference,
                "region": self.region,
                "data_boundary": self.data_boundary,
                "concurrency_limit": self.concurrency_limit,
                "enabled": self.enabled,
                "version": self.version,
            }
        )

    def next_version(self, *, enabled: bool) -> ProviderConnection:
        now = _now()
        return replace(
            self,
            enabled=enabled,
            version=self.version + 1,
            created_at=now,
            updated_at=now,
        )


@dataclass(frozen=True)
class ModelDeployment:
    """One immutable model revision bound to an exact connection version."""

    deployment_id: str
    organization_id: str
    connection_id: str
    connection_version: int
    model_id: str
    model_family: str
    max_context_tokens: int
    max_output_tokens: int
    structured_output: bool = True
    tool_capabilities: tuple[str, ...] = ()
    status: str = "active"
    revision: int = 1
    created_at: datetime = field(default_factory=_now)
    updated_at: datetime = field(default_factory=_now)

    def __post_init__(self) -> None:
        _identifier("deployment_id", self.deployment_id)
        _identifier("organization_id", self.organization_id)
        _identifier("connection_id", self.connection_id)
        _text("model_id", self.model_id)
        _text("model_family", self.model_family)
        if (
            min(
                self.connection_version,
                self.max_context_tokens,
                self.max_output_tokens,
                self.revision,
            )
            < 1
        ):
            raise ValueError("deployment versions and token limits must be positive")
        _ordered("tool_capabilities", self.tool_capabilities)
        if self.status not in _DEPLOYMENT_STATES:
            raise ValueError("unsupported deployment status")
        _aware("created_at", self.created_at)
        _aware("updated_at", self.updated_at)

    @property
    def fingerprint(self) -> str:
        return _fingerprint(
            {
                "deployment_id": self.deployment_id,
                "organization_id": self.organization_id,
                "connection_id": self.connection_id,
                "connection_version": self.connection_version,
                "model_id": self.model_id,
                "model_family": self.model_family,
                "max_context_tokens": self.max_context_tokens,
                "max_output_tokens": self.max_output_tokens,
                "structured_output": self.structured_output,
                "tool_capabilities": list(self.tool_capabilities),
                "status": self.status,
                "revision": self.revision,
            }
        )

    def next_revision(self, *, status: str) -> ModelDeployment:
        now = _now()
        return replace(
            self,
            status=status,
            revision=self.revision + 1,
            created_at=now,
            updated_at=now,
        )


@dataclass(frozen=True)
class BotProfile:
    """One selectable bot identity bound to an AI-1 declaration and deployment."""

    bot_profile_id: str
    organization_id: str
    agent_identity: str
    display_name: str
    deployment_id: str
    deployment_revision: int
    prompt_version: str
    capabilities: tuple[str, ...]
    permitted_tools: tuple[str, ...] = ()
    data_policy: BotDataPolicy = field(default_factory=BotDataPolicy)
    budget_policy: BotBudgetPolicy = field(default_factory=BotBudgetPolicy)
    concurrency_limit: int = 1
    enabled: bool = False
    version: int = 1
    created_at: datetime = field(default_factory=_now)
    updated_at: datetime = field(default_factory=_now)

    def __post_init__(self) -> None:
        _identifier("bot_profile_id", self.bot_profile_id)
        _identifier("organization_id", self.organization_id)
        if not _SHA256.fullmatch(self.agent_identity):
            raise ValueError("agent_identity must be a SHA-256 identity")
        _text("display_name", self.display_name)
        _identifier("deployment_id", self.deployment_id)
        _text("prompt_version", self.prompt_version)
        _ordered("capabilities", self.capabilities)
        _ordered("permitted_tools", self.permitted_tools)
        if not self.capabilities:
            raise ValueError("bot profile requires at least one capability")
        if min(self.deployment_revision, self.concurrency_limit, self.version) < 1:
            raise ValueError("profile versions and concurrency must be positive")
        _aware("created_at", self.created_at)
        _aware("updated_at", self.updated_at)

    @property
    def fingerprint(self) -> str:
        return _fingerprint(
            {
                "bot_profile_id": self.bot_profile_id,
                "organization_id": self.organization_id,
                "agent_identity": self.agent_identity,
                "display_name": self.display_name,
                "deployment_id": self.deployment_id,
                "deployment_revision": self.deployment_revision,
                "prompt_version": self.prompt_version,
                "capabilities": list(self.capabilities),
                "permitted_tools": list(self.permitted_tools),
                "data_policy": self.data_policy.canonical(),
                "budget_policy": self.budget_policy.canonical(),
                "concurrency_limit": self.concurrency_limit,
                "enabled": self.enabled,
                "version": self.version,
            }
        )

    def next_version(self, *, enabled: bool) -> BotProfile:
        now = _now()
        return replace(
            self,
            enabled=enabled,
            version=self.version + 1,
            created_at=now,
            updated_at=now,
        )
