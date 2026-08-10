"""Security-first execution sandbox abstraction for Phase 6."""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Mapping, Protocol, Tuple

from phase6.execution.audit import AuditSink, ExecutionAuditEvent, utc_timestamp


class SandboxError(RuntimeError):
    """Base error for sandbox contract violations."""


class UnknownSandboxAdapter(SandboxError):
    """Raised when an execution adapter is not explicitly registered."""


class InvalidExecutionSpec(ValueError, SandboxError):
    """Raised for invalid execution specs while preserving legacy ValueError compatibility."""


class ExecutionOutcome(str, Enum):
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    TIMED_OUT = "timed_out"
    REJECTED = "rejected"


@dataclass(frozen=True)
class ExecutionLimits:
    """Hard resource limits supplied by trusted runtime code."""

    wall_time_seconds: float = 30.0
    cpu_time_seconds: float = 10.0
    memory_bytes: int = 256 * 1024 * 1024
    process_count: int = 1
    output_bytes: int = 1024 * 1024
    file_size_bytes: int = 16 * 1024 * 1024
    open_file_count: int = 64

    def __post_init__(self) -> None:
        if self.wall_time_seconds <= 0:
            raise ValueError("wall_time_seconds must be positive")
        if self.cpu_time_seconds <= 0:
            raise ValueError("cpu_time_seconds must be positive")
        for name in (
            "memory_bytes", "process_count", "output_bytes", "file_size_bytes", "open_file_count"
        ):
            if getattr(self, name) <= 0:
                raise ValueError(f"{name} must be positive")
        if self.cpu_time_seconds > self.wall_time_seconds:
            raise ValueError("cpu_time_seconds cannot exceed wall_time_seconds")
        if self.output_bytes > self.file_size_bytes:
            raise ValueError("output_bytes cannot exceed file_size_bytes")


@dataclass(frozen=True)
class ExecutionSecurityContext:
    """Immutable authority context passed into an isolated executor."""

    organization_id: str
    principal_id: str
    actor_id: str
    capabilities: Tuple[str, ...] = ()
    secret_references: Tuple[str, ...] = ()

    def __post_init__(self) -> None:
        for name in ("organization_id", "principal_id", "actor_id"):
            if not getattr(self, name).strip():
                raise ValueError(f"{name} must be non-empty")
        if any(not value.strip() for value in self.capabilities):
            raise ValueError("capabilities must not contain empty values")
        if any(not value.strip() for value in self.secret_references):
            raise ValueError("secret_references must not contain empty values")
        if len(self.capabilities) != len(set(self.capabilities)):
            raise ValueError("capabilities must be unique")
        if len(self.secret_references) != len(set(self.secret_references)):
            raise ValueError("secret_references must be unique")


@dataclass(frozen=True)
class ExecutionSpec:
    """Fully bounded execution request crossing into the sandbox."""

    execution_id: str
    adapter_id: str
    argv: Tuple[str, ...]
    security: ExecutionSecurityContext
    limits: ExecutionLimits = ExecutionLimits()
    read_only_paths: Tuple[str, ...] = ()
    writable_paths: Tuple[str, ...] = ()
    network_allowlist: Tuple[str, ...] = ()
    environment: Tuple[Tuple[str, str], ...] = ()

    def __post_init__(self) -> None:
        if not self.execution_id.strip():
            raise ValueError("execution_id must be non-empty")
        if not self.adapter_id.strip():
            raise ValueError("adapter_id must be non-empty")
        if not self.argv or any(not argument.strip() for argument in self.argv):
            raise ValueError("argv must contain non-empty arguments")
        if any(not path.strip() for path in self.read_only_paths):
            raise ValueError("read_only_paths must not contain empty values")
        if any(not path.strip() for path in self.writable_paths):
            raise ValueError("writable_paths must not contain empty values")
        if any(not host.strip() for host in self.network_allowlist):
            raise ValueError("network_allowlist must not contain empty values")
        keys = [key for key, _ in self.environment]
        if any(not key.strip() for key in keys):
            raise ValueError("environment keys must be non-empty")
        if len(keys) != len(set(keys)):
            raise ValueError("environment keys must be unique")
        if any("=" in argument for argument in self.argv):
            raise ValueError("argv entries must be arguments, not environment assignments")
        if "*" in self.network_allowlist:
            raise ValueError("network_allowlist cannot use wildcard access")
        if set(self.writable_paths) & set(self.read_only_paths):
            raise InvalidExecutionSpec("a path cannot be both writable and read-only")


@dataclass(frozen=True)
class ExecutionResult:
    """Bounded result returned from an isolated executor."""

    execution_id: str
    adapter_id: str
    outcome: ExecutionOutcome
    output: str = ""
    error: str | None = None
    exit_code: int | None = None

    def __post_init__(self) -> None:
        if not self.execution_id.strip():
            raise ValueError("execution_id must be non-empty")
        if not self.adapter_id.strip():
            raise ValueError("adapter_id must be non-empty")
        if self.outcome is ExecutionOutcome.SUCCEEDED and self.error:
            raise ValueError("successful execution cannot contain an error")


class SandboxAdapter(Protocol):
    adapter_id: str

    def execute(self, spec: ExecutionSpec) -> ExecutionResult:
        """Execute exactly the supplied bounded specification."""


class Sandbox(Protocol):
    def execute(self, spec: ExecutionSpec) -> ExecutionResult:
        """Resolve an allowlisted adapter and execute the specification."""


class SandboxRegistry:
    """Allowlist of concrete sandbox adapters with audit lifecycle events."""

    def __init__(self, adapters: Mapping[str, SandboxAdapter] | None = None, audit_sink: AuditSink | None = None) -> None:
        self._adapters: dict[str, SandboxAdapter] = {}
        self._audit = audit_sink
        for adapter_id, adapter in (adapters or {}).items():
            self.register(adapter_id, adapter)

    def register(self, adapter_id: str, adapter: SandboxAdapter) -> None:
        if not adapter_id.strip():
            raise ValueError("adapter_id must be non-empty")
        if adapter_id != adapter.adapter_id:
            raise ValueError("registry key must match adapter.adapter_id")
        if adapter_id in self._adapters:
            raise ValueError(f"adapter already registered: {adapter_id}")
        self._adapters[adapter_id] = adapter

    def resolve(self, adapter_id: str) -> SandboxAdapter:
        try:
            return self._adapters[adapter_id]
        except KeyError as exc:
            raise UnknownSandboxAdapter(adapter_id) from exc

    def execute(self, spec: ExecutionSpec) -> ExecutionResult:
        self._emit(spec, "execution.started", "started")
        adapter = self.resolve(spec.adapter_id)
        try:
            result = adapter.execute(spec)
        except ValueError as exc:
            self._emit(spec, "execution.rejected", "rejected", error_code="invalid_execution_spec")
            raise InvalidExecutionSpec(str(exc)) from exc
        if result.execution_id != spec.execution_id:
            self._emit(spec, "execution.rejected", "rejected", error_code="execution_id_mismatch")
            raise InvalidExecutionSpec("adapter returned a different execution_id")
        if result.adapter_id != spec.adapter_id:
            self._emit(spec, "execution.rejected", "rejected", error_code="adapter_id_mismatch")
            raise InvalidExecutionSpec("adapter returned a different adapter_id")
        if len(result.output.encode("utf-8")) > spec.limits.output_bytes:
            self._emit(spec, "execution.rejected", "rejected", error_code="output_limit")
            raise InvalidExecutionSpec("adapter returned output above configured limit")
        self._emit(spec, "execution.finished", result.outcome.value, exit_code=result.exit_code)
        return result

    def _emit(self, spec: ExecutionSpec, event_type: str, outcome: str, *, error_code: str | None = None, exit_code: int | None = None) -> None:
        if self._audit is None:
            return
        self._audit.emit(ExecutionAuditEvent(
            event_type=event_type,
            execution_id=spec.execution_id,
            adapter_id=spec.adapter_id,
            outcome=outcome,
            timestamp=utc_timestamp(),
            error_code=error_code,
            exit_code=exit_code,
        ))

    @property
    def adapter_ids(self) -> Tuple[str, ...]:
        return tuple(sorted(self._adapters))
