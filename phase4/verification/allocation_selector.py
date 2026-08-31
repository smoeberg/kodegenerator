"""Deterministic, auditable Council bot selection.

Selection consumes immutable configuration and catalog snapshots.  It never
calls a model and never mutates the configured allocation pools.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Mapping

from phase4.council.configuration import (
    CouncilTemplate,
    IndependenceLevel,
    RoleAllocationPool,
)

_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _fingerprint(value: Any) -> str:
    encoded = json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode()
    return hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True)
class SelectionCandidate:
    bot_profile_id: str
    bot_profile_version: int
    profile_fingerprint: str
    agent_identity: str
    deployment_id: str
    deployment_revision: int
    deployment_fingerprint: str
    connection_id: str
    connection_version: int
    connection_fingerprint: str
    provider: str
    brand: str
    model_family: str
    data_boundary: str
    region: str | None
    capabilities: tuple[str, ...]
    enabled: bool
    deployment_status: str

    def __post_init__(self) -> None:
        if not _ID.fullmatch(self.bot_profile_id):
            raise ValueError("candidate profile ID is invalid")
        if min(
            self.bot_profile_version,
            self.deployment_revision,
            self.connection_version,
        ) < 1:
            raise ValueError("candidate versions must be positive")


@dataclass(frozen=True)
class SelectionRequestContext:
    organization_id: str
    scope_id: str
    repository: str
    base_sha: str
    requirements_fingerprint: str
    architecture_fingerprint: str
    contract_fingerprint: str
    input_fingerprint: str
    template_fingerprint: str

    def __post_init__(self) -> None:
        if not _ID.fullmatch(self.organization_id) or not _ID.fullmatch(self.scope_id):
            raise ValueError("selection context identity is invalid")
        if not self.repository.strip() or self.repository != self.repository.strip():
            raise ValueError("repository must be canonical non-empty text")
        if not re.fullmatch(r"[a-f0-9]{40}", self.base_sha):
            raise ValueError("base SHA must be an exact Git SHA-1")
        fingerprints = (
            self.requirements_fingerprint,
            self.architecture_fingerprint,
            self.contract_fingerprint,
            self.input_fingerprint,
            self.template_fingerprint,
        )
        if any(not re.fullmatch(r"[a-f0-9]{64}", value) for value in fingerprints):
            raise ValueError("context fingerprints must be SHA-256 values")

    @property
    def fingerprint(self) -> str:
        return _fingerprint(self.__dict__)


@dataclass(frozen=True)
class SelectionReceipt:
    stage_id: str
    role_id: str
    role_version: int
    allocation_id: str
    allocation_version: int
    bot_profile_id: str
    bot_profile_version: int
    accepted: bool
    reason: str
    preference_rank: int


@dataclass(frozen=True)
class FrozenCouncilAssignment:
    assignment_id: str
    stage_id: str
    role_id: str
    role_version: int
    allocation_id: str
    allocation_version: int
    bot_profile_id: str
    bot_profile_version: int
    profile_fingerprint: str
    agent_identity: str
    deployment_id: str
    deployment_revision: int
    deployment_fingerprint: str
    connection_id: str
    connection_version: int
    connection_fingerprint: str
    scope_id: str
    repository: str
    base_sha: str
    input_fingerprint: str


@dataclass(frozen=True)
class CouncilRunSelection:
    run_id: str
    organization_id: str
    template_id: str
    template_version: int
    template_fingerprint: str
    context_fingerprint: str
    scope_id: str
    repository: str
    base_sha: str
    input_fingerprint: str
    assignments: tuple[FrozenCouncilAssignment, ...]
    receipts: tuple[SelectionReceipt, ...]
    status: str = "selected"
    rationale: str = "selection constraints satisfied"
    selector_version: str = "deterministic-v1"
    created_at: datetime = field(default_factory=_now)

    def __post_init__(self) -> None:
        if self.status not in {"selected", "blocked"}:
            raise ValueError("selection status is invalid")
        if self.status == "blocked" and self.assignments:
            raise ValueError("blocked selection cannot contain assignments")
        if self.status == "selected" and not self.assignments:
            raise ValueError("selected decision requires an assignment")
        fingerprints = (
            self.template_fingerprint,
            self.context_fingerprint,
        )
        if any(not re.fullmatch(r"[a-f0-9]{64}", value) for value in fingerprints):
            raise ValueError("selection fingerprints must be SHA-256 values")
        if not self.rationale.strip():
            raise ValueError("selection rationale is required")

    @property
    def fingerprint(self) -> str:
        return _fingerprint(
            {
                "organization_id": self.organization_id,
                "template_id": self.template_id,
                "template_version": self.template_version,
                "template_fingerprint": self.template_fingerprint,
                "context_fingerprint": self.context_fingerprint,
                "scope_id": self.scope_id,
                "repository": self.repository,
                "base_sha": self.base_sha,
                "input_fingerprint": self.input_fingerprint,
                "selector_version": self.selector_version,
                "status": self.status,
                "rationale": self.rationale,
                "assignments": [assignment.__dict__ for assignment in self.assignments],
                "receipts": [receipt.__dict__ for receipt in self.receipts],
            }
        )


class CouncilSelectionError(RuntimeError):
    """Raised when configured constraints cannot produce a valid Council."""


class DeterministicCouncilSelector:
    """Select exact bot revisions using only stable configured inputs."""

    version = "deterministic-v1"

    def select(
        self,
        *,
        run_id: str,
        organization_id: str,
        template: CouncilTemplate,
        allocations: Mapping[tuple[str, int], RoleAllocationPool],
        candidates: Mapping[tuple[str, int], SelectionCandidate],
        context: SelectionRequestContext,
    ) -> CouncilRunSelection:
        if template.organization_id != organization_id or not template.enabled:
            raise CouncilSelectionError("template is unavailable for organization")
        if not _ID.fullmatch(run_id):
            raise CouncilSelectionError("run ID is invalid")
        if (
            context.organization_id != organization_id
            or context.template_fingerprint != template.fingerprint
        ):
            raise CouncilSelectionError("selection context does not bind template")
        assignments: list[FrozenCouncilAssignment] = []
        receipts: list[SelectionReceipt] = []
        blocked: list[str] = []
        for stage in template.stages:
            selected_keys: set[str] = set()
            stage_count = 0
            for role_key in stage.role_versions:
                pool = allocations.get(role_key)
                if pool is None or not pool.enabled:
                    raise CouncilSelectionError(
                        f"no enabled allocation for role {role_key[0]}:{role_key[1]}"
                    )
                if pool.organization_id != organization_id:
                    raise CouncilSelectionError(
                        "allocation crosses organization boundary"
                    )
                for member in sorted(
                    pool.members,
                    key=lambda value: (
                        value.preference_rank,
                        value.bot_profile_id,
                        value.bot_profile_version,
                    ),
                ):
                    candidate = candidates.get(
                        (member.bot_profile_id, member.bot_profile_version)
                    )
                    if stage_count >= stage.maximum_assignments:
                        accepted, reason = False, "stage_capacity_reached"
                    else:
                        accepted, reason = self._evaluate(
                            candidate, pool, selected_keys
                        )
                    receipts.append(
                        SelectionReceipt(
                            stage.stage_id,
                            pool.role_id,
                            pool.role_version,
                            pool.allocation_id,
                            pool.version,
                            member.bot_profile_id,
                            member.bot_profile_version,
                            accepted,
                            reason,
                            member.preference_rank,
                        )
                    )
                    if not accepted or candidate is None:
                        continue
                    selected_keys.add(self._independence_key(candidate, pool))
                    assignments.append(
                        self._assignment(
                            context,
                            stage.stage_id,
                            pool,
                            candidate,
                        )
                    )
                    stage_count += 1
            if stage_count < stage.minimum_assignments:
                blocked.append(
                    f"stage {stage.stage_id} requires {stage.minimum_assignments} "
                    f"assignments but only {stage_count} satisfy policy"
                )
        status = "blocked" if blocked else "selected"
        return CouncilRunSelection(
            run_id=run_id,
            organization_id=organization_id,
            template_id=template.template_id,
            template_version=template.version,
            template_fingerprint=template.fingerprint,
            context_fingerprint=context.fingerprint,
            scope_id=context.scope_id,
            repository=context.repository,
            base_sha=context.base_sha,
            input_fingerprint=context.input_fingerprint,
            assignments=() if blocked else tuple(assignments),
            receipts=tuple(receipts),
            status=status,
            rationale=(
                "; ".join(blocked)
                if blocked
                else "selection constraints satisfied"
            ),
            selector_version=self.version,
        )

    @staticmethod
    def _evaluate(candidate, pool, selected_keys) -> tuple[bool, str]:
        if candidate is None:
            return False, "profile_snapshot_missing"
        if not candidate.enabled or candidate.deployment_status != "active":
            return False, "candidate_inactive"
        constraints = dict(pool.hard_constraints)
        supported = {"brand", "provider", "model_family", "data_boundary", "region"}
        unknown = set(constraints) - supported
        if unknown:
            raise CouncilSelectionError(
                f"unsupported hard constraints: {', '.join(sorted(unknown))}"
            )
        for name, expected in constraints.items():
            if getattr(candidate, name) != expected:
                return False, f"hard_constraint:{name}"
        key = DeterministicCouncilSelector._independence_key(candidate, pool)
        if key in selected_keys:
            return False, f"independence:{pool.independence_level.value}"
        return True, "selected"

    @staticmethod
    def _independence_key(candidate, pool) -> str:
        values = {
            IndependenceLevel.PROFILE: (
                candidate.bot_profile_id,
                candidate.bot_profile_version,
            ),
            IndependenceLevel.CONNECTION: (
                candidate.connection_id,
                candidate.connection_version,
            ),
            IndependenceLevel.MODEL_FAMILY: (candidate.model_family,),
            IndependenceLevel.PROVIDER: (candidate.provider,),
            IndependenceLevel.BRAND: (candidate.brand,),
            IndependenceLevel.DEPLOYMENT: (
                candidate.deployment_id,
                candidate.deployment_revision,
            ),
        }
        return _fingerprint(values[pool.independence_level])

    @staticmethod
    def _assignment(
        context, stage_id, pool, candidate
    ) -> FrozenCouncilAssignment:
        assignment_id = _fingerprint(
            [
                context.fingerprint,
                context.template_fingerprint,
                stage_id,
                pool.role_id,
                pool.role_version,
                pool.allocation_id,
                pool.version,
                candidate.bot_profile_id,
                candidate.bot_profile_version,
                candidate.profile_fingerprint,
                candidate.deployment_fingerprint,
                candidate.connection_fingerprint,
            ]
        )
        return FrozenCouncilAssignment(
            assignment_id=assignment_id,
            stage_id=stage_id,
            role_id=pool.role_id,
            role_version=pool.role_version,
            allocation_id=pool.allocation_id,
            allocation_version=pool.version,
            bot_profile_id=candidate.bot_profile_id,
            bot_profile_version=candidate.bot_profile_version,
            profile_fingerprint=candidate.profile_fingerprint,
            agent_identity=candidate.agent_identity,
            deployment_id=candidate.deployment_id,
            deployment_revision=candidate.deployment_revision,
            deployment_fingerprint=candidate.deployment_fingerprint,
            connection_id=candidate.connection_id,
            connection_version=candidate.connection_version,
            connection_fingerprint=candidate.connection_fingerprint,
            scope_id=context.scope_id,
            repository=context.repository,
            base_sha=context.base_sha,
            input_fingerprint=context.input_fingerprint,
        )
