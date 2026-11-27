# domain/agent_job.py
"""Job record for every agent job in the pipeline.

Completion plan, step 1 and "Agentstatistik": every agent job gets a job
record so the system can later learn which agent, model and prompt version
handles which task type best. The record is opened when a task is created,
marked started when a worker claims it, and closed exactly once per attempt.

Fields that are not known yet (model, prompt version, rule version, usage)
are recorded as ``None`` rather than guessed. The measurements are written by
the controls (fact check, level 1, level 2, rework loop, mandate check, daily
review); the record never computes them from an agent's own report.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from domain.requirements_provenance import RequirementsRef

#: Measurements defined by the completion plan. Each key is written by the
#: control named in the plan; an absent key means "not measured yet".
MEASUREMENT_KEYS: tuple[str, ...] = (
    "fabricated_references",  # fact check
    "unverified_claims",  # fact check
    "out_of_scope_changes",  # fact check
    "level1_first_pass",  # level 1
    "level2_first_pass",  # level 2
    "rework_rounds",  # rework loop
    "later_deviations",  # mandate check
    "discarded",  # daily review
    "marked_assumptions",  # delivery
)


class AgentJobRecordError(ValueError):
    """Raised on an invalid job record or an illegal state change."""


class AgentJobStatus(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    REJECTED_STALE = "rejected_stale"


_CLOSED = frozenset(
    {AgentJobStatus.SUCCEEDED, AgentJobStatus.FAILED, AgentJobStatus.REJECTED_STALE}
)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def _parse(value: Any) -> datetime | None:
    if value in (None, ""):
        return None
    return datetime.fromisoformat(str(value))


@dataclass(frozen=True)
class AgentIdentity:
    """Who did the job. Only non-secret identity is recorded."""

    tool: str
    worker_id: str | None = None
    bot_profile_id: str | None = None
    provider: str | None = None
    model: str | None = None
    model_version: str | None = None
    #: Model producer (anthropic, openai, mistral, ...); the independence
    #: dimension of the role-process principle (domain/role_process.py).
    brand: str | None = None
    #: Agent session the job ran in; control roles need a different one.
    session_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "tool": self.tool,
            "worker_id": self.worker_id,
            "bot_profile_id": self.bot_profile_id,
            "provider": self.provider,
            "model": self.model,
            "model_version": self.model_version,
            "brand": self.brand,
            "session_id": self.session_id,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> AgentIdentity:
        return cls(
            tool=str(data["tool"]),
            worker_id=data.get("worker_id"),
            bot_profile_id=data.get("bot_profile_id"),
            provider=data.get("provider"),
            model=data.get("model"),
            model_version=data.get("model_version"),
            brand=data.get("brand"),
            session_id=data.get("session_id"),
        )


#: Identity used until the worker adapter (step 6) binds a real coding agent.
DOR_PIPELINE_EXECUTOR = "dor-pipeline-executor"


@dataclass(frozen=True)
class AgentJobRecord:
    job_id: str
    organization_id: str | None
    workflow_id: str
    task_id: str
    task_type: str
    role: str
    attempt: int
    requirements: RequirementsRef | None
    agent: AgentIdentity = field(
        default_factory=lambda: AgentIdentity(tool=DOR_PIPELINE_EXECUTOR)
    )
    status: AgentJobStatus = AgentJobStatus.QUEUED
    stack: str | None = None
    prompt_version: str | None = None
    rule_version: str | None = None
    #: Work package the job belongs to; control jobs carry the id of the
    #: package they control. Defaults to the task id.
    work_package_id: str | None = None
    created_at: datetime = field(default_factory=_now)
    started_at: datetime | None = None
    finished_at: datetime | None = None
    error: str | None = None
    usage: Mapping[str, Any] = field(default_factory=dict)
    measurements: Mapping[str, Any] = field(default_factory=dict)
    #: Non-secret evidence of the agent call (prompt and output fingerprints,
    #: request id); the full agent log arrives with the worker adapter.
    provenance: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.attempt < 1:
            raise AgentJobRecordError("attempt must be >= 1")
        unknown = set(self.measurements) - set(MEASUREMENT_KEYS)
        if unknown:
            raise AgentJobRecordError(f"unknown measurements: {sorted(unknown)}")

    @property
    def closed(self) -> bool:
        return self.status in _CLOSED

    @property
    def duration_seconds(self) -> float | None:
        if self.started_at is None or self.finished_at is None:
            return None
        return (self.finished_at - self.started_at).total_seconds()

    def start(self, worker_id: str, at: datetime | None = None) -> AgentJobRecord:
        if self.closed:
            raise AgentJobRecordError(f"job {self.job_id} is already closed")
        return replace(
            self,
            status=AgentJobStatus.RUNNING,
            started_at=at or _now(),
            agent=replace(self.agent, worker_id=worker_id),
        )

    def close(
        self,
        status: AgentJobStatus,
        *,
        error: str | None = None,
        usage: Mapping[str, Any] | None = None,
        at: datetime | None = None,
    ) -> AgentJobRecord:
        if status not in _CLOSED:
            raise AgentJobRecordError(f"{status.value} is not a closing status")
        if self.closed:
            raise AgentJobRecordError(f"job {self.job_id} is already closed")
        finished = at or _now()
        return replace(
            self,
            status=status,
            finished_at=finished,
            # A job that was never seen starting is timed from creation.
            started_at=self.started_at or self.created_at,
            error=error,
            usage=dict(usage) if usage else dict(self.usage),
        )

    def bind_agent(self, agent: AgentIdentity) -> AgentJobRecord:
        if self.closed:
            raise AgentJobRecordError(f"job {self.job_id} is already closed")
        return replace(self, agent=agent)

    def record_measurements(self, values: Mapping[str, Any]) -> AgentJobRecord:
        merged = {**dict(self.measurements), **dict(values)}
        return replace(self, measurements=merged)

    def to_dict(self) -> dict[str, Any]:
        return {
            "job_id": self.job_id,
            "organization_id": self.organization_id,
            "workflow_id": self.workflow_id,
            "task_id": self.task_id,
            "task_type": self.task_type,
            "role": self.role,
            "attempt": self.attempt,
            "requirements": self.requirements.to_dict() if self.requirements else None,
            "agent": self.agent.to_dict(),
            "status": self.status.value,
            "stack": self.stack,
            "prompt_version": self.prompt_version,
            "rule_version": self.rule_version,
            "work_package_id": self.work_package_id,
            "created_at": _iso(self.created_at),
            "started_at": _iso(self.started_at),
            "finished_at": _iso(self.finished_at),
            "duration_seconds": self.duration_seconds,
            "error": self.error,
            "usage": dict(self.usage),
            "measurements": dict(self.measurements),
            "provenance": dict(self.provenance),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> AgentJobRecord:
        try:
            requirements = data.get("requirements")
            return cls(
                job_id=str(data["job_id"]),
                organization_id=data.get("organization_id"),
                workflow_id=str(data["workflow_id"]),
                task_id=str(data["task_id"]),
                task_type=str(data["task_type"]),
                role=str(data["role"]),
                attempt=int(data["attempt"]),
                requirements=RequirementsRef.from_dict(requirements)
                if requirements
                else None,
                agent=AgentIdentity.from_dict(data["agent"]),
                status=AgentJobStatus(data["status"]),
                stack=data.get("stack"),
                prompt_version=data.get("prompt_version"),
                rule_version=data.get("rule_version"),
                work_package_id=data.get("work_package_id"),
                created_at=_parse(data["created_at"]) or _now(),
                started_at=_parse(data.get("started_at")),
                finished_at=_parse(data.get("finished_at")),
                error=data.get("error"),
                usage=dict(data.get("usage") or {}),
                measurements=dict(data.get("measurements") or {}),
                provenance=dict(data.get("provenance") or {}),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise AgentJobRecordError(f"invalid job record: {exc}") from exc


def job_id_for(task_id: str, attempt: int) -> str:
    return f"job-{task_id}-a{attempt}"
