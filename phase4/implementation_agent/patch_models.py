"""Immutable contracts for governed application of validated patch proposals."""

from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path, PurePosixPath

from phase4.authority.models import AuthorityRequest
from phase4.execution.models import ExecutionRequest

from .models import ImplementationContractError, PatchProposal

IMPLEMENTATION_APPLY_ACTION = "implementation.apply_patch"
_HEX_DIGEST = re.compile(r"^[0-9a-f]{64}$")


class PatchExecutionContractError(ImplementationContractError):
    """A governed patch-execution value is malformed or insufficiently bound."""


class ToolKind(str, Enum):
    LINT = "lint"
    TEST = "test"
    BUILD = "build"


class ToolStatus(str, Enum):
    PASSED = "passed"
    FAILED = "failed"
    TIMED_OUT = "timed_out"
    OUTPUT_LIMIT = "output_limit"
    START_ERROR = "start_error"


class PatchRecordStatus(str, Enum):
    SUCCEEDED = "succeeded"
    FAILED = "failed"


def canonical_digest(value: object) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def validate_repository_path(path: str) -> str:
    if not isinstance(path, str) or not path.strip() or path != path.strip():
        raise PatchExecutionContractError("repository paths must be canonical non-empty strings")
    if "\\" in path:
        raise PatchExecutionContractError("repository paths must be canonical POSIX paths")
    candidate = PurePosixPath(path)
    if candidate.is_absolute() or path.startswith("/"):
        raise PatchExecutionContractError("repository paths must be relative")
    if not candidate.parts or any(part in {"", ".", ".."} for part in candidate.parts):
        raise PatchExecutionContractError("repository paths cannot contain traversal segments")
    if candidate.as_posix() != path:
        raise PatchExecutionContractError("repository paths must be canonical POSIX paths")
    return path


@dataclass(frozen=True, order=True)
class WorkspaceFileState:
    """Content identity for one touched path at one workspace state."""
    path: str
    exists: bool
    sha256: str | None
    byte_count: int
    mode: int | None

    def __post_init__(self) -> None:
        object.__setattr__(self, "path", validate_repository_path(self.path))
        if type(self.exists) is not bool:
            raise TypeError("exists must be a boolean")
        if type(self.byte_count) is not int or self.byte_count < 0:
            raise PatchExecutionContractError("byte_count must be a non-negative integer")
        if self.exists:
            if not isinstance(self.sha256, str) or not _HEX_DIGEST.fullmatch(self.sha256):
                raise PatchExecutionContractError("existing files require a lowercase SHA-256 digest")
            if type(self.mode) is not int or self.mode < 0:
                raise PatchExecutionContractError("existing files require a non-negative mode")
        elif self.sha256 is not None or self.byte_count != 0 or self.mode is not None:
            raise PatchExecutionContractError("absent files cannot declare content metadata")

    def canonical(self) -> dict[str, object]:
        return {"path": self.path, "exists": self.exists, "sha256": self.sha256, "byte_count": self.byte_count, "mode": self.mode}


def workspace_fingerprint(states: tuple[WorkspaceFileState, ...]) -> str:
    return canonical_digest([state.canonical() for state in states])


@dataclass(frozen=True)
class TrustedToolSpec:
    """Operator-owned fixed command; API and agents can reference no argv values."""
    tool_id: str
    kind: ToolKind
    command: tuple[str, ...]
    timeout_seconds: int = 300
    max_output_bytes: int = 256 * 1024
    environment: tuple[tuple[str, str], ...] = ()
    executable_sha256: str = field(init=False)

    def __post_init__(self) -> None:
        if not isinstance(self.tool_id, str) or not self.tool_id.strip() or self.tool_id != self.tool_id.strip():
            raise PatchExecutionContractError("tool_id must be canonical and non-empty")
        if not isinstance(self.kind, ToolKind):
            raise TypeError("kind must be a ToolKind")
        if not isinstance(self.command, tuple) or not self.command:
            raise PatchExecutionContractError("trusted tool command must not be empty")
        if any(not isinstance(argument, str) or not argument or "\x00" in argument or "\n" in argument for argument in self.command):
            raise PatchExecutionContractError("trusted tool arguments must be non-empty canonical strings")
        if not Path(self.command[0]).is_absolute():
            raise PatchExecutionContractError("trusted tool executable must be an absolute path")
        try:
            executable_path = Path(self.command[0]).resolve(strict=True)
            executable_sha256 = _sha256_file(executable_path)
        except OSError as exc:
            raise PatchExecutionContractError("trusted tool executable must be an existing regular file") from exc
        if not os.access(executable_path, os.X_OK):
            raise PatchExecutionContractError("trusted tool executable must have execute permission")
        for name in ("timeout_seconds", "max_output_bytes"):
            value = getattr(self, name)
            if type(value) is not int or value < 1:
                raise PatchExecutionContractError(f"{name} must be a positive integer")
        if not isinstance(self.environment, tuple) or any(not isinstance(item, tuple) or len(item) != 2 for item in self.environment):
            raise PatchExecutionContractError("trusted tool environment must contain key/value tuples")
        environment = tuple(sorted(self.environment))
        keys = tuple(key for key, _ in environment)
        if len(keys) != len(set(keys)):
            raise PatchExecutionContractError("trusted tool environment keys must be unique")
        for key, value in environment:
            if not isinstance(key, str) or not key or not key.replace("_", "").isalnum() or not isinstance(value, str) or "\x00" in value:
                raise PatchExecutionContractError("trusted tool environment values must be canonical strings")
        object.__setattr__(self, "environment", environment)
        object.__setattr__(self, "executable_sha256", executable_sha256)

    @property
    def tool_fingerprint(self) -> str:
        return canonical_digest({"tool_id": self.tool_id, "kind": self.kind.value, "command": list(self.command), "executable_sha256": self.executable_sha256, "timeout_seconds": self.timeout_seconds, "max_output_bytes": self.max_output_bytes, "environment": list(self.environment)})

    def canonical(self) -> dict[str, object]:
        return {"tool_id": self.tool_id, "kind": self.kind.value, "tool_fingerprint": self.tool_fingerprint}

    def executable_matches(self) -> bool:
        try:
            current = _sha256_file(Path(self.command[0]).resolve(strict=True))
        except OSError:
            return False
        return current == self.executable_sha256


def toolchain_fingerprint(tools: tuple[TrustedToolSpec, ...]) -> str:
    return canonical_digest([tool.canonical() for tool in tools])


def _sha256_file(path: Path) -> str:
    if not path.is_file():
        raise OSError("path is not a regular file")
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


@dataclass(frozen=True)
class PatchExecutionRequest:
    """Exact AI-3/AI-4 request for applying one validated proposal."""
    proposal: PatchProposal
    baseline: tuple[WorkspaceFileState, ...]
    tools: tuple[TrustedToolSpec, ...]
    request_fingerprint: str = field(init=False)
    baseline_fingerprint: str = field(init=False)
    toolchain_fingerprint: str = field(init=False)

    def __post_init__(self) -> None:
        if not isinstance(self.proposal, PatchProposal):
            raise TypeError("proposal must be a PatchProposal")
        if any(not isinstance(item, WorkspaceFileState) for item in self.baseline):
            raise TypeError("baseline must contain WorkspaceFileState values")
        baseline = tuple(sorted(self.baseline, key=lambda item: item.path))
        if tuple(item.path for item in baseline) != self.proposal.touched_paths:
            raise PatchExecutionContractError("baseline paths must exactly match proposal touched paths")
        if any(not isinstance(tool, TrustedToolSpec) for tool in self.tools):
            raise TypeError("tools must contain TrustedToolSpec values")
        tools = tuple(self.tools)
        if not tools:
            raise PatchExecutionContractError("patch execution requires trusted tools")
        tool_ids = tuple(tool.tool_id for tool in tools)
        if len(tool_ids) != len(set(tool_ids)):
            raise PatchExecutionContractError("trusted tool IDs must be unique")
        kinds = {tool.kind for tool in tools}
        if kinds != {ToolKind.LINT, ToolKind.TEST, ToolKind.BUILD}:
            raise PatchExecutionContractError("toolchain must contain lint, test, and build evidence")
        baseline_id = workspace_fingerprint(baseline)
        toolchain_id = toolchain_fingerprint(tools)
        request_id = canonical_digest({"action": IMPLEMENTATION_APPLY_ACTION, "proposal_id": self.proposal.proposal_id, "proposal_request_fingerprint": self.proposal.request_fingerprint, "diff_sha256": self.proposal.diff_sha256, "baseline_fingerprint": baseline_id, "toolchain_fingerprint": toolchain_id, "resource": self.proposal.request.resource, "context_packet_id": self.proposal.request.context_packet_id, "organization_id": self.proposal.request.organization_id})
        object.__setattr__(self, "baseline", baseline)
        object.__setattr__(self, "tools", tools)
        object.__setattr__(self, "baseline_fingerprint", baseline_id)
        object.__setattr__(self, "toolchain_fingerprint", toolchain_id)
        object.__setattr__(self, "request_fingerprint", request_id)

    @property
    def agent_identity(self) -> str:
        return self.proposal.request.agent_identity

    @property
    def agent_role(self) -> str:
        return self.proposal.request.agent_role

    @property
    def organization_id(self) -> str:
        return self.proposal.request.organization_id

    @property
    def resource(self) -> str:
        return self.proposal.request.resource

    @property
    def context_packet_id(self) -> str:
        return self.proposal.request.context_packet_id

    def authority_context(self) -> dict[str, str]:
        return {"organization_id": self.organization_id, "patch_execution_request_fingerprint": self.request_fingerprint, "proposal_id": self.proposal.proposal_id, "proposal_request_fingerprint": self.proposal.request_fingerprint, "diff_sha256": self.proposal.diff_sha256, "baseline_fingerprint": self.baseline_fingerprint, "toolchain_fingerprint": self.toolchain_fingerprint}

    def execution_parameters(self) -> dict[str, str]:
        return {"patch_execution_request_fingerprint": self.request_fingerprint, "organization_id": self.organization_id}

    def authority_request(self) -> AuthorityRequest:
        return AuthorityRequest.create(agent_identity=self.agent_identity, agent_role=self.agent_role, action=IMPLEMENTATION_APPLY_ACTION, resource=self.resource, context_packet_id=self.context_packet_id, context=self.authority_context(), parameters=self.execution_parameters())

    def execution_request(self, *, idempotency_key: str | None = None) -> ExecutionRequest:
        authority = self.authority_request()
        return ExecutionRequest.create(request_id=authority.request_id, agent_identity=self.agent_identity, action=IMPLEMENTATION_APPLY_ACTION, resource=self.resource, context_packet_id=self.context_packet_id, organization_id=self.organization_id, parameters=self.execution_parameters(), idempotency_key=idempotency_key)
