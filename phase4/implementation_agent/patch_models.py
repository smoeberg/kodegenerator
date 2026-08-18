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
    encoded = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def validate_repository_path(path: str) -> str:
    if not isinstance(path, str) or not path.strip() or path != path.strip():
        raise PatchExecutionContractError(
            "repository paths must be canonical non-empty strings"
        )
    if "\\" in path:
        raise PatchExecutionContractError(
            "repository paths must be canonical POSIX paths"
        )
    candidate = PurePosixPath(path)
    if candidate.is_absolute() or path.startswith("/"):
        raise PatchExecutionContractError("repository paths must be relative")
    if not candidate.parts or any(part in {"", ".", ".."} for part in candidate.parts):
        raise PatchExecutionContractError(
            "repository paths cannot contain traversal segments"
        )
    if candidate.as_posix() != path:
        raise PatchExecutionContractError(
            "repository paths must be canonical POSIX paths"
        )
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
            raise PatchExecutionContractError(
                "byte_count must be a non-negative integer"
            )
        if self.exists:
            if not isinstance(self.sha256, str) or not _HEX_DIGEST.fullmatch(
                self.sha256
            ):
                raise PatchExecutionContractError(
                    "existing files require a lowercase SHA-256 digest"
                )
            if type(self.mode) is not int or self.mode < 0:
                raise PatchExecutionContractError(
                    "existing files require a non-negative mode"
                )
        elif self.sha256 is not None or self.byte_count != 0 or self.mode is not None:
            raise PatchExecutionContractError(
                "absent files cannot declare content metadata"
            )

    def canonical(self) -> dict[str, object]:
        return {
            "path": self.path,
            "exists": self.exists,
            "sha256": self.sha256,
            "byte_count": self.byte_count,
            "mode": self.mode,
        }


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
        if (
            not isinstance(self.tool_id, str)
            or not self.tool_id.strip()
            or self.tool_id != self.tool_id.strip()
        ):
            raise PatchExecutionContractError("tool_id must be canonical and non-empty")
        if not isinstance(self.kind, ToolKind):
            raise TypeError("kind must be a ToolKind")
        if not isinstance(self.command, tuple) or not self.command:
            raise PatchExecutionContractError("trusted tool command must not be empty")
        if any(
            not isinstance(argument, str)
            or not argument
            or "\x00" in argument
            or "\n" in argument
            for argument in self.command
        ):
            raise PatchExecutionContractError(
                "trusted tool arguments must be non-empty canonical strings"
            )
        if not Path(self.command[0]).is_absolute():
            raise PatchExecutionContractError(
                "trusted tool executable must be an absolute path"
            )
        try:
            executable_path = Path(self.command[0]).resolve(strict=True)
            executable_sha256 = _sha256_file(executable_path)
        except OSError as exc:
            raise PatchExecutionContractError(
                "trusted tool executable must be an existing regular file"
            ) from exc
        if not os.access(executable_path, os.X_OK):
            raise PatchExecutionContractError(
                "trusted tool executable must have execute permission"
            )
        for name in ("timeout_seconds", "max_output_bytes"):
            value = getattr(self, name)
            if type(value) is not int or value < 1:
                raise PatchExecutionContractError(f"{name} must be a positive integer")
        if not isinstance(self.environment, tuple) or any(
            not isinstance(item, tuple) or len(item) != 2 for item in self.environment
        ):
            raise PatchExecutionContractError(
                "trusted tool environment must contain key/value tuples"
            )
        environment = tuple(sorted(self.environment))
        keys = tuple(key for key, _ in environment)
        if len(keys) != len(set(keys)):
            raise PatchExecutionContractError(
                "trusted tool environment keys must be unique"
            )
        for key, value in environment:
            if (
                not isinstance(key, str)
                or not key
                or not key.replace("_", "").isalnum()
                or not isinstance(value, str)
                or "\x00" in value
            ):
                raise PatchExecutionContractError(
                    "trusted tool environment values must be canonical strings"
                )
        object.__setattr__(self, "environment", environment)
        object.__setattr__(self, "executable_sha256", executable_sha256)

    @property
    def tool_fingerprint(self) -> str:
        return canonical_digest(
            {
                "tool_id": self.tool_id,
                "kind": self.kind.value,
                "command": list(self.command),
                "executable_sha256": self.executable_sha256,
                "timeout_seconds": self.timeout_seconds,
                "max_output_bytes": self.max_output_bytes,
                "environment": list(self.environment),
            }
        )

    def canonical(self) -> dict[str, object]:
        return {
            "tool_id": self.tool_id,
            "kind": self.kind.value,
            "tool_fingerprint": self.tool_fingerprint,
        }

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
            raise PatchExecutionContractError(
                "baseline paths must exactly match proposal touched paths"
            )
        if any(not isinstance(tool, TrustedToolSpec) for tool in self.tools):
            raise TypeError("tools must contain TrustedToolSpec values")
        tools = tuple(self.tools)
        if not tools:
            raise PatchExecutionContractError("patch execution requires trusted tools")
        tool_ids = tuple(tool.tool_id for tool in tools)
        if len(tool_ids) != len(set(tool_ids)):
            raise PatchExecutionContractError("trusted tool IDs must be unique")
        kinds = {tool.kind for tool in tools}
        required = {ToolKind.LINT, ToolKind.TEST, ToolKind.BUILD}
        if kinds != required:
            raise PatchExecutionContractError(
                "toolchain must contain lint, test, and build evidence"
            )
        baseline_id = workspace_fingerprint(baseline)
        toolchain_id = toolchain_fingerprint(tools)
        request_id = canonical_digest(
            {
                "action": IMPLEMENTATION_APPLY_ACTION,
                "proposal_id": self.proposal.proposal_id,
                "proposal_request_fingerprint": self.proposal.request_fingerprint,
                "diff_sha256": self.proposal.diff_sha256,
                "baseline_fingerprint": baseline_id,
                "toolchain_fingerprint": toolchain_id,
                "resource": self.proposal.request.resource,
                "context_packet_id": self.proposal.request.context_packet_id,
            }
        )
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
    def resource(self) -> str:
        return self.proposal.request.resource

    @property
    def context_packet_id(self) -> str:
        return self.proposal.request.context_packet_id

    def authority_context(self) -> dict[str, str]:
        return {
            "patch_execution_request_fingerprint": self.request_fingerprint,
            "proposal_id": self.proposal.proposal_id,
            "proposal_request_fingerprint": self.proposal.request_fingerprint,
            "diff_sha256": self.proposal.diff_sha256,
            "baseline_fingerprint": self.baseline_fingerprint,
            "toolchain_fingerprint": self.toolchain_fingerprint,
        }

    def execution_parameters(self) -> dict[str, str]:
        """Return the immutable parameters shared by AI-3 and AI-4."""
        return {
            "patch_execution_request_fingerprint": self.request_fingerprint,
        }

    def authority_request(self) -> AuthorityRequest:
        return AuthorityRequest.create(
            agent_identity=self.agent_identity,
            agent_role=self.agent_role,
            action=IMPLEMENTATION_APPLY_ACTION,
            resource=self.resource,
            context_packet_id=self.context_packet_id,
            context=self.authority_context(),
            parameters=self.execution_parameters(),
        )

    def execution_request(
        self, *, idempotency_key: str | None = None
    ) -> ExecutionRequest:
        authority = self.authority_request()
        return ExecutionRequest.create(
            request_id=authority.request_id,
            agent_identity=self.agent_identity,
            action=IMPLEMENTATION_APPLY_ACTION,
            resource=self.resource,
            context_packet_id=self.context_packet_id,
            parameters=self.execution_parameters(),
            idempotency_key=idempotency_key,
        )


@dataclass(frozen=True)
class LogArtifact:
    """Bounded log preview plus the digest of the complete captured stream."""

    stream: str
    sha256: str
    byte_count: int
    content: str
    truncated: bool

    def __post_init__(self) -> None:
        if self.stream not in {"stdout", "stderr"}:
            raise PatchExecutionContractError("log stream must be stdout or stderr")
        if not _HEX_DIGEST.fullmatch(self.sha256):
            raise PatchExecutionContractError("log SHA-256 is invalid")
        if type(self.byte_count) is not int or self.byte_count < 0:
            raise PatchExecutionContractError("log byte_count is invalid")
        if not isinstance(self.content, str) or type(self.truncated) is not bool:
            raise TypeError("log content and truncated flag have invalid types")

    @property
    def artifact_id(self) -> str:
        return canonical_digest(
            {
                "stream": self.stream,
                "sha256": self.sha256,
                "byte_count": self.byte_count,
                "content": self.content,
                "truncated": self.truncated,
            }
        )


@dataclass(frozen=True)
class PatchArtifact:
    """Content-addressed candidate workspace state for the touched paths."""

    proposal_id: str
    diff_sha256: str
    baseline_fingerprint: str
    files: tuple[WorkspaceFileState, ...]
    artifact_id: str = field(init=False)

    def __post_init__(self) -> None:
        for name in ("proposal_id", "diff_sha256", "baseline_fingerprint"):
            value = getattr(self, name)
            if not isinstance(value, str) or not _HEX_DIGEST.fullmatch(value):
                raise PatchExecutionContractError(f"{name} must be a SHA-256 digest")
        if any(not isinstance(item, WorkspaceFileState) for item in self.files):
            raise TypeError("artifact files must contain WorkspaceFileState values")
        files = tuple(sorted(self.files, key=lambda item: item.path))
        if not files or len(files) != len({item.path for item in files}):
            raise PatchExecutionContractError(
                "artifact files must be non-empty and unique"
            )
        object.__setattr__(self, "files", files)
        object.__setattr__(
            self,
            "artifact_id",
            canonical_digest(
                {
                    "proposal_id": self.proposal_id,
                    "diff_sha256": self.diff_sha256,
                    "baseline_fingerprint": self.baseline_fingerprint,
                    "files": [item.canonical() for item in files],
                }
            ),
        )


@dataclass(frozen=True)
class ToolEvidence:
    """Non-authoritative evidence from one fixed trusted tool execution."""

    tool_id: str
    kind: ToolKind
    tool_fingerprint: str
    artifact_id: str
    status: ToolStatus
    exit_code: int | None
    stdout: LogArtifact
    stderr: LogArtifact
    evidence_id: str = field(init=False)

    def __post_init__(self) -> None:
        if not isinstance(self.tool_id, str) or not self.tool_id.strip():
            raise PatchExecutionContractError("tool evidence requires a tool_id")
        if not isinstance(self.kind, ToolKind) or not isinstance(
            self.status, ToolStatus
        ):
            raise TypeError("tool evidence enum values are invalid")
        for name in ("tool_fingerprint", "artifact_id"):
            value = getattr(self, name)
            if not isinstance(value, str) or not _HEX_DIGEST.fullmatch(value):
                raise PatchExecutionContractError(f"{name} must be a SHA-256 digest")
        if self.exit_code is not None and type(self.exit_code) is not int:
            raise TypeError("exit_code must be an integer or None")
        if not isinstance(self.stdout, LogArtifact) or not isinstance(
            self.stderr, LogArtifact
        ):
            raise TypeError("tool evidence requires immutable stdout/stderr logs")
        object.__setattr__(
            self,
            "evidence_id",
            canonical_digest(
                {
                    "tool_id": self.tool_id,
                    "kind": self.kind.value,
                    "tool_fingerprint": self.tool_fingerprint,
                    "artifact_id": self.artifact_id,
                    "status": self.status.value,
                    "exit_code": self.exit_code,
                    "stdout_artifact_id": self.stdout.artifact_id,
                    "stderr_artifact_id": self.stderr.artifact_id,
                }
            ),
        )

    @property
    def passed(self) -> bool:
        return self.status is ToolStatus.PASSED


@dataclass(frozen=True)
class PatchExecutionRecord:
    """Immutable patch/apply attempt and its candidate evidence."""

    request_fingerprint: str
    proposal_id: str
    baseline_fingerprint: str
    status: PatchRecordStatus
    artifact: PatchArtifact | None
    evidence: tuple[ToolEvidence, ...]
    committed: bool
    rolled_back: bool
    error: str | None = None
    record_id: str = field(init=False)

    def __post_init__(self) -> None:
        for name in ("request_fingerprint", "proposal_id", "baseline_fingerprint"):
            value = getattr(self, name)
            if not isinstance(value, str) or not _HEX_DIGEST.fullmatch(value):
                raise PatchExecutionContractError(f"{name} must be a SHA-256 digest")
        if not isinstance(self.status, PatchRecordStatus):
            raise TypeError("status must be a PatchRecordStatus")
        if self.artifact is not None and not isinstance(self.artifact, PatchArtifact):
            raise TypeError("artifact must be a PatchArtifact or None")
        if any(not isinstance(item, ToolEvidence) for item in self.evidence):
            raise TypeError("evidence must contain ToolEvidence values")
        if type(self.committed) is not bool or type(self.rolled_back) is not bool:
            raise TypeError("committed and rolled_back must be booleans")
        if self.status is PatchRecordStatus.SUCCEEDED:
            if self.artifact is None or not self.committed or self.rolled_back:
                raise PatchExecutionContractError(
                    "successful records require a committed artifact"
                )
            if not self.evidence or any(not item.passed for item in self.evidence):
                raise PatchExecutionContractError(
                    "successful records require passing tool evidence"
                )
            if self.error is not None:
                raise PatchExecutionContractError(
                    "successful records cannot contain an error"
                )
        else:
            if self.committed:
                raise PatchExecutionContractError("failed records cannot be committed")
            if not isinstance(self.error, str) or not self.error.strip():
                raise PatchExecutionContractError(
                    "failed records require a non-empty error"
                )
        object.__setattr__(
            self,
            "record_id",
            canonical_digest(
                {
                    "request_fingerprint": self.request_fingerprint,
                    "proposal_id": self.proposal_id,
                    "baseline_fingerprint": self.baseline_fingerprint,
                    "status": self.status.value,
                    "artifact_id": self.artifact.artifact_id
                    if self.artifact is not None
                    else None,
                    "evidence_ids": [item.evidence_id for item in self.evidence],
                    "committed": self.committed,
                    "rolled_back": self.rolled_back,
                    "error": self.error,
                }
            ),
        )
