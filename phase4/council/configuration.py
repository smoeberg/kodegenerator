"""Provider-neutral, immutable Council configuration values."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from enum import Enum
from typing import Any

_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _id(name: str, value: str) -> str:
    if not isinstance(value, str) or not _IDENTIFIER.fullmatch(value):
        raise ValueError(f"{name} must be a canonical identifier")
    return value


def _text(name: str, value: str) -> str:
    if not isinstance(value, str) or not value.strip() or value != value.strip():
        raise ValueError(f"{name} must be canonical non-empty text")
    return value


def _ordered(name: str, values: tuple[str, ...], *, required: bool = False) -> None:
    if required and not values:
        raise ValueError(f"{name} must not be empty")
    if values != tuple(sorted(set(values))) or any(not item.strip() for item in values):
        raise ValueError(f"{name} must be sorted, unique, and non-empty")


def _aware(value: datetime) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("timestamps must be timezone-aware")


def _fingerprint(payload: dict[str, Any]) -> str:
    encoded = json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


class ProtocolFunction(str, Enum):
    CONVERSATION_OWNER = "conversation_owner"
    PROPOSER = "proposer"
    REVIEWER = "reviewer"
    VERIFIER = "verifier"
    IMPLEMENTER = "implementer"
    CANDIDATE_EVALUATOR = "candidate_evaluator"
    INTEGRATOR = "integrator"


class IndependenceLevel(str, Enum):
    PROFILE = "profile"
    CONNECTION = "connection"
    MODEL_FAMILY = "model_family"
    PROVIDER = "provider"
    BRAND = "brand"
    DEPLOYMENT = "deployment"


class AutonomyLevel(int, Enum):
    HUMAN_DECIDES = 0
    HUMAN_APPROVES = 1
    HUMAN_REVIEWS_EXCEPTIONS = 2
    GOVERNED_AUTONOMY = 3
    HIGH_AUTONOMY = 4
    FULL_POLICY_AUTONOMY = 5


@dataclass(frozen=True)
class CouncilRoleDefinition:
    role_id: str
    organization_id: str
    name: str
    purpose: str
    protocol_function: ProtocolFunction
    required_capabilities: tuple[str, ...]
    output_schema_ref: str
    rubric_ref: str
    input_schema_ref: str | None = None
    independent_verification: bool = True
    enabled: bool = True
    version: int = 1
    created_at: datetime = field(default_factory=_now)

    def __post_init__(self) -> None:
        _id("role_id", self.role_id)
        _id("organization_id", self.organization_id)
        _text("name", self.name)
        _text("purpose", self.purpose)
        _ordered("required_capabilities", self.required_capabilities, required=True)
        _text("output_schema_ref", self.output_schema_ref)
        _text("rubric_ref", self.rubric_ref)
        if self.input_schema_ref is not None:
            _text("input_schema_ref", self.input_schema_ref)
        if self.version < 1:
            raise ValueError("version must be positive")
        _aware(self.created_at)

    @property
    def fingerprint(self) -> str:
        return _fingerprint(self.canonical())

    def canonical(self) -> dict[str, Any]:
        return {
            "role_id": self.role_id,
            "organization_id": self.organization_id,
            "name": self.name,
            "purpose": self.purpose,
            "protocol_function": self.protocol_function.value,
            "required_capabilities": list(self.required_capabilities),
            "input_schema_ref": self.input_schema_ref,
            "output_schema_ref": self.output_schema_ref,
            "rubric_ref": self.rubric_ref,
            "independent_verification": self.independent_verification,
            "enabled": self.enabled,
            "version": self.version,
        }

    def next_version(self, *, enabled: bool) -> CouncilRoleDefinition:
        return replace(
            self, enabled=enabled, version=self.version + 1, created_at=_now()
        )


@dataclass(frozen=True)
class TemplateStage:
    stage_id: str
    protocol_function: ProtocolFunction
    role_versions: tuple[tuple[str, int], ...]
    minimum_assignments: int = 1
    maximum_assignments: int = 1
    parallel: bool = False
    blocking: bool = True

    def __post_init__(self) -> None:
        _id("stage_id", self.stage_id)
        if not self.role_versions or self.role_versions != tuple(
            sorted(set(self.role_versions))
        ):
            raise ValueError("role_versions must be sorted, unique, and non-empty")
        for role_id, version in self.role_versions:
            _id("role_id", role_id)
            if version < 1:
                raise ValueError("role version must be positive")
        if (
            self.minimum_assignments < 1
            or self.maximum_assignments < self.minimum_assignments
        ):
            raise ValueError("stage assignment bounds are invalid")

    def canonical(self) -> dict[str, Any]:
        return {
            "stage_id": self.stage_id,
            "protocol_function": self.protocol_function.value,
            "role_versions": [[role, version] for role, version in self.role_versions],
            "minimum_assignments": self.minimum_assignments,
            "maximum_assignments": self.maximum_assignments,
            "parallel": self.parallel,
            "blocking": self.blocking,
        }


@dataclass(frozen=True)
class CouncilTemplate:
    template_id: str
    organization_id: str
    name: str
    stages: tuple[TemplateStage, ...]
    approved_by: str
    enabled: bool = True
    version: int = 1
    created_at: datetime = field(default_factory=_now)

    def __post_init__(self) -> None:
        _id("template_id", self.template_id)
        _id("organization_id", self.organization_id)
        _text("name", self.name)
        _id("approved_by", self.approved_by)
        if not self.stages or len({stage.stage_id for stage in self.stages}) != len(
            self.stages
        ):
            raise ValueError("template stages must be non-empty with unique IDs")
        if self.version < 1:
            raise ValueError("version must be positive")
        _aware(self.created_at)

    @property
    def fingerprint(self) -> str:
        return _fingerprint(
            {
                "template_id": self.template_id,
                "organization_id": self.organization_id,
                "name": self.name,
                "stages": [stage.canonical() for stage in self.stages],
                "approved_by": self.approved_by,
                "enabled": self.enabled,
                "version": self.version,
            }
        )


@dataclass(frozen=True)
class AllocationMember:
    bot_profile_id: str
    bot_profile_version: int
    preference_rank: int
    fallback_rank: int | None = None

    def __post_init__(self) -> None:
        _id("bot_profile_id", self.bot_profile_id)
        if self.bot_profile_version < 1 or self.preference_rank < 1:
            raise ValueError("profile version and preference rank must be positive")
        if self.fallback_rank is not None and self.fallback_rank < 1:
            raise ValueError("fallback rank must be positive")

    def canonical(self) -> dict[str, Any]:
        return {
            "bot_profile_id": self.bot_profile_id,
            "bot_profile_version": self.bot_profile_version,
            "preference_rank": self.preference_rank,
            "fallback_rank": self.fallback_rank,
        }


@dataclass(frozen=True)
class RoleAllocationPool:
    allocation_id: str
    organization_id: str
    role_id: str
    role_version: int
    members: tuple[AllocationMember, ...]
    independence_level: IndependenceLevel
    autonomy_level: AutonomyLevel
    approved_by: str
    hard_constraints: tuple[tuple[str, Any], ...] = ()
    enabled: bool = True
    version: int = 1
    created_at: datetime = field(default_factory=_now)

    def __post_init__(self) -> None:
        _id("allocation_id", self.allocation_id)
        _id("organization_id", self.organization_id)
        _id("role_id", self.role_id)
        _id("approved_by", self.approved_by)
        if min(self.role_version, self.version) < 1:
            raise ValueError("versions must be positive")
        if not self.members or len(
            {(m.bot_profile_id, m.bot_profile_version) for m in self.members}
        ) != len(self.members):
            raise ValueError("allocation members must be non-empty and unique")
        ranks = [member.preference_rank for member in self.members]
        if len(set(ranks)) != len(ranks):
            raise ValueError("preference ranks must be unique")
        if self.hard_constraints != tuple(
            sorted(self.hard_constraints, key=lambda item: item[0])
        ):
            raise ValueError("hard constraints must be key-sorted")
        _aware(self.created_at)

    @property
    def fingerprint(self) -> str:
        return _fingerprint(
            {
                "allocation_id": self.allocation_id,
                "organization_id": self.organization_id,
                "role_id": self.role_id,
                "role_version": self.role_version,
                "members": [m.canonical() for m in self.members],
                "independence_level": self.independence_level.value,
                "autonomy_level": self.autonomy_level.value,
                "hard_constraints": dict(self.hard_constraints),
                "approved_by": self.approved_by,
                "enabled": self.enabled,
                "version": self.version,
            }
        )
