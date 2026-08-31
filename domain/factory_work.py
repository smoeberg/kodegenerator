"""Immutable work-package and candidate-delivery contracts for the factory."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from enum import Enum
from typing import Any

_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_SHA256 = re.compile(r"^[a-f0-9]{64}$")
_SHA1 = re.compile(r"^[a-f0-9]{40}$")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def fingerprint(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(
            value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
        ).encode()
    ).hexdigest()


def _id(name: str, value: str) -> None:
    if not _ID.fullmatch(value):
        raise ValueError(f"{name} must be a canonical identifier")


class ExecutionMode(str, Enum):
    SINGLE = "single"
    COMPETING = "competing"


class WorkPackageStatus(str, Enum):
    BLOCKED = "blocked"
    READY = "ready"
    PUBLISHED = "published"
    RUNNING = "running"
    DELIVERED = "delivered"
    FAILED = "failed"


@dataclass(frozen=True)
class WriteScope:
    allowed_paths: tuple[str, ...]
    denied_paths: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        for values in (self.allowed_paths, self.denied_paths):
            if values != tuple(sorted(set(values))) or any(
                not item or item.startswith("/") or ".." in item.split("/")
                for item in values
            ):
                raise ValueError("write scopes must be sorted unique relative paths")
        if not self.allowed_paths:
            raise ValueError("at least one allowed path is required")

    def overlaps(self, other: WriteScope) -> bool:
        return any(
            left == right
            or left.startswith(right.rstrip("/") + "/")
            or right.startswith(left.rstrip("/") + "/")
            for left in self.allowed_paths
            for right in other.allowed_paths
        )


@dataclass(frozen=True)
class WorkPackage:
    organization_id: str
    work_package_id: str
    logical_task_id: str
    workflow_id: str
    requirements_fingerprint: str
    architecture_fingerprint: str
    contract_fingerprint: str
    base_sha: str
    dependency_ids: tuple[str, ...]
    criterion_ids: tuple[str, ...]
    required_checks: tuple[str, ...]
    write_scope: WriteScope
    execution_mode: ExecutionMode
    candidate_count: int
    allocation_id: str
    allocation_version: int
    policy_fingerprint: str
    token_budget: int
    time_budget_seconds: int
    idempotency_key: str
    status: WorkPackageStatus
    version: int = 0
    created_at: datetime = field(default_factory=_now)

    def __post_init__(self) -> None:
        for name in (
            "organization_id",
            "work_package_id",
            "logical_task_id",
            "workflow_id",
            "allocation_id",
        ):
            _id(name, getattr(self, name))
        for name in (
            "requirements_fingerprint",
            "architecture_fingerprint",
            "contract_fingerprint",
            "policy_fingerprint",
        ):
            if not _SHA256.fullmatch(getattr(self, name)):
                raise ValueError(f"{name} must be a SHA-256 fingerprint")
        if not _SHA1.fullmatch(self.base_sha):
            raise ValueError("base_sha must be an exact Git SHA-1")
        for values in (self.dependency_ids, self.criterion_ids, self.required_checks):
            if values != tuple(sorted(set(values))):
                raise ValueError("package lists must be sorted and unique")
        if not self.criterion_ids or not self.required_checks:
            raise ValueError("criteria and deterministic checks are required")
        if (
            self.candidate_count < 1
            or self.allocation_version < 1
            or min(self.token_budget, self.time_budget_seconds) < 1
        ):
            raise ValueError("package counts, versions, and budgets must be positive")
        if self.execution_mode is ExecutionMode.SINGLE and self.candidate_count != 1:
            raise ValueError("single mode requires exactly one candidate")
        if self.execution_mode is ExecutionMode.COMPETING and self.candidate_count < 2:
            raise ValueError("competing mode requires at least two candidates")
        if self.version < 0 or not self.idempotency_key.strip():
            raise ValueError("package version or idempotency key is invalid")

    @property
    def content_fingerprint(self) -> str:
        return fingerprint(
            {
                "organization_id": self.organization_id,
                "work_package_id": self.work_package_id,
                "logical_task_id": self.logical_task_id,
                "workflow_id": self.workflow_id,
                "requirements_fingerprint": self.requirements_fingerprint,
                "architecture_fingerprint": self.architecture_fingerprint,
                "contract_fingerprint": self.contract_fingerprint,
                "base_sha": self.base_sha,
                "dependency_ids": self.dependency_ids,
                "criterion_ids": self.criterion_ids,
                "required_checks": self.required_checks,
                "write_scope": self.write_scope.__dict__,
                "execution_mode": self.execution_mode.value,
                "candidate_count": self.candidate_count,
                "allocation": [self.allocation_id, self.allocation_version],
                "policy_fingerprint": self.policy_fingerprint,
                "token_budget": self.token_budget,
                "time_budget_seconds": self.time_budget_seconds,
                "idempotency_key": self.idempotency_key,
            }
        )

    def transition(self, target: WorkPackageStatus) -> WorkPackage:
        allowed = {
            WorkPackageStatus.BLOCKED: {
                WorkPackageStatus.READY,
                WorkPackageStatus.FAILED,
            },
            WorkPackageStatus.READY: {
                WorkPackageStatus.PUBLISHED,
                WorkPackageStatus.FAILED,
            },
            WorkPackageStatus.PUBLISHED: {
                WorkPackageStatus.RUNNING,
                WorkPackageStatus.FAILED,
            },
            WorkPackageStatus.RUNNING: {
                WorkPackageStatus.DELIVERED,
                WorkPackageStatus.FAILED,
            },
            WorkPackageStatus.DELIVERED: set(),
            WorkPackageStatus.FAILED: set(),
        }
        if target not in allowed[self.status]:
            raise ValueError(
                f"invalid work-package transition: {self.status} -> {target}"
            )
        return replace(self, status=target, version=self.version + 1)


@dataclass(frozen=True)
class CandidateDelivery:
    organization_id: str
    candidate_id: str
    work_package_id: str
    work_package_fingerprint: str
    execution_id: str
    assignment_id: str
    base_sha: str
    branch: str
    head_sha: str
    commit_shas: tuple[str, ...]
    patch_fingerprint: str
    affected_paths: tuple[str, ...]
    attestations: tuple[str, ...]
    delivered_at: datetime = field(default_factory=_now)

    def __post_init__(self) -> None:
        for name in (
            "organization_id",
            "candidate_id",
            "work_package_id",
            "execution_id",
        ):
            _id(name, getattr(self, name))
        for name in ("work_package_fingerprint", "assignment_id", "patch_fingerprint"):
            if not _SHA256.fullmatch(getattr(self, name)):
                raise ValueError(f"{name} must be a SHA-256 fingerprint")
        if not _SHA1.fullmatch(self.base_sha) or not _SHA1.fullmatch(self.head_sha):
            raise ValueError("candidate base/head must be exact Git SHA-1 values")
        if not self.commit_shas or any(
            not _SHA1.fullmatch(item) for item in self.commit_shas
        ):
            raise ValueError("candidate requires ordered exact commit SHAs")
        if (
            self.affected_paths != tuple(sorted(set(self.affected_paths)))
            or not self.attestations
        ):
            raise ValueError("candidate paths or attestations are invalid")

    @property
    def content_fingerprint(self) -> str:
        return fingerprint(
            {
                key: value
                for key, value in self.__dict__.items()
                if key != "delivered_at"
            }
        )


@dataclass(frozen=True)
class CandidateSelection:
    organization_id: str
    selection_id: str
    logical_task_id: str
    work_package_fingerprint: str
    candidate_ids: tuple[str, ...]
    rubric_fingerprint: str
    evaluation_ids: tuple[str, ...]
    excluded_candidate_ids: tuple[str, ...]
    winner_candidate_id: str | None
    evaluator_assignment_id: str
    authority_decision_id: str
    created_at: datetime = field(default_factory=_now)

    def __post_init__(self) -> None:
        _id("organization_id", self.organization_id)
        _id("logical_task_id", self.logical_task_id)
        for name in (
            "selection_id",
            "work_package_fingerprint",
            "rubric_fingerprint",
            "evaluator_assignment_id",
            "authority_decision_id",
        ):
            if not _SHA256.fullmatch(getattr(self, name)):
                raise ValueError(f"{name} must be a SHA-256 fingerprint")
        if (
            self.candidate_ids != tuple(sorted(set(self.candidate_ids)))
            or not self.candidate_ids
        ):
            raise ValueError("candidate IDs must be sorted, unique, and non-empty")
        for candidate_id in self.candidate_ids:
            _id("candidate_id", candidate_id)
        for values in (self.evaluation_ids, self.excluded_candidate_ids):
            if values != tuple(sorted(set(values))):
                raise ValueError("selection evidence must be sorted and unique")
        if not set(self.excluded_candidate_ids).issubset(self.candidate_ids):
            raise ValueError("excluded candidates must be part of the selection")
        if (
            self.winner_candidate_id is not None
            and self.winner_candidate_id not in self.candidate_ids
        ):
            raise ValueError("winner must be one of the evaluated candidates")
        if set(self.excluded_candidate_ids) & (
            {self.winner_candidate_id} if self.winner_candidate_id else set()
        ):
            raise ValueError("excluded candidate cannot be selected")

    @property
    def content_fingerprint(self) -> str:
        return fingerprint(
            {
                key: value
                for key, value in self.__dict__.items()
                if key not in {"selection_id", "created_at"}
            }
        )
