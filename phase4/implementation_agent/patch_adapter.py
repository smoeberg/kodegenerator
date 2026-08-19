"""Trusted AI-4 adapter for bounded patch application and tool evidence."""

from __future__ import annotations

import hashlib
import os
import secrets
import shutil
import stat
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from threading import RLock
from typing import ClassVar, Protocol

from phase4.execution.adapters import AdapterResult
from phase4.execution.models import ExecutionRequest

from .models import PatchProposal
from .patch_models import (
    IMPLEMENTATION_APPLY_ACTION,
    LogArtifact,
    PatchArtifact,
    PatchExecutionContractError,
    PatchExecutionRecord,
    PatchExecutionRequest,
    PatchRecordStatus,
    ToolEvidence,
    ToolKind,
    ToolStatus,
    TrustedToolSpec,
    WorkspaceFileState,
    validate_repository_path,
)


class PatchWorkspaceError(RuntimeError):
    """The workspace cannot be read or changed within the approved boundary."""


class PatchExecutionAdapterError(RuntimeError):
    """The AI-4 patch adapter rejected or failed an execution."""


class PatchExecutionRequestNotFoundError(PatchExecutionAdapterError):
    """AI-4 referenced no operator-registered patch request."""


class PatchExecutionRequestBindingError(PatchExecutionAdapterError):
    """AI-4 input was not exactly bound to the registered patch request."""


class PatchExecutionFailed(PatchExecutionAdapterError):
    """A governed patch attempt failed after producing an immutable record."""

    def __init__(self, record: PatchExecutionRecord) -> None:
        self.record = record
        super().__init__(record.error or "governed patch execution failed")


@dataclass(frozen=True)
class RawToolResult:
    status: ToolStatus
    exit_code: int | None
    stdout: bytes = b""
    stderr: bytes = b""

    def __post_init__(self) -> None:
        if not isinstance(self.status, ToolStatus):
            raise TypeError("status must be a ToolStatus")
        if self.exit_code is not None and type(self.exit_code) is not int:
            raise TypeError("exit_code must be an integer or None")
        if not isinstance(self.stdout, bytes) or not isinstance(self.stderr, bytes):
            raise TypeError("tool output must be bytes")


class ToolRunner(Protocol):
    def run(self, tool: TrustedToolSpec, *, cwd: Path) -> RawToolResult: ...


class SubprocessToolRunner:
    _ENVIRONMENT: ClassVar[dict[str, str]] = {
        "PATH": os.defpath,
        "PYTHONHASHSEED": "0",
        "PYTHONDONTWRITEBYTECODE": "1",
        "LC_ALL": "C.UTF-8",
        "LANG": "C.UTF-8",
    }

    def run(self, tool: TrustedToolSpec, *, cwd: Path) -> RawToolResult:
        if not isinstance(tool, TrustedToolSpec):
            raise TypeError("tool must be a TrustedToolSpec")
        if not isinstance(cwd, Path) or not cwd.is_dir():
            raise PatchWorkspaceError("trusted tool cwd must be an existing directory")
        if not tool.executable_matches():
            return RawToolResult(ToolStatus.START_ERROR, None, b"", b"trusted tool executable no longer matches its configured fingerprint")
        try:
            environment = dict(self._ENVIRONMENT)
            environment.update(dict(tool.environment))
            completed = subprocess.run(
                tool.command,
                cwd=cwd,
                env=environment,
                capture_output=True,
                timeout=tool.timeout_seconds,
                check=False,
                shell=False,
            )
        except subprocess.TimeoutExpired as exc:
            return RawToolResult(ToolStatus.TIMED_OUT, None, _as_bytes(exc.stdout), _as_bytes(exc.stderr))
        except OSError as exc:
            return RawToolResult(ToolStatus.START_ERROR, None, b"", str(exc).encode("utf-8", errors="replace"))
        stdout, stderr = completed.stdout, completed.stderr
        if len(stdout) > tool.max_output_bytes or len(stderr) > tool.max_output_bytes:
            status = ToolStatus.OUTPUT_LIMIT
        elif completed.returncode == 0:
            status = ToolStatus.PASSED
        else:
            status = ToolStatus.FAILED
        return RawToolResult(status, completed.returncode, stdout, stderr)


@dataclass(frozen=True)
class _FileSnapshot:
    state: WorkspaceFileState
    content: bytes | None


_EXCLUDED_DIRECTORY_NAMES = frozenset({".git", ".hg", ".svn", ".venv", "venv", "env", "node_modules", "__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache", "htmlcov"})
_EXCLUDED_FILE_NAMES = frozenset({".env", ".env.local", ".env.production", ".coverage", "dor_runtime.db"})
_EXCLUDED_FILE_SUFFIXES = (".key", ".pem", ".sqlite", ".sqlite3")


class WorkspacePatchExecutor:
    """Validate in a copy, then replace only approved live paths."""

    def __init__(self, root: Path, *, tool_runner: ToolRunner | None = None, max_workspace_files: int = 10000, max_workspace_bytes: int = 64 * 1024 * 1024, max_file_bytes: int = 8 * 1024 * 1024, patch_timeout_seconds: int = 30, git_executable: str | None = None) -> None:
        self._root = _validated_root(root)
        self._tool_runner = tool_runner or SubprocessToolRunner()
        self._max_workspace_files = max_workspace_files
        self._max_workspace_bytes = max_workspace_bytes
        self._max_file_bytes = max_file_bytes
        self._patch_timeout_seconds = patch_timeout_seconds
        self._git = git_executable or shutil.which("git") or "/usr/bin/git"
        self._git_sha256 = _file_sha256(Path(self._git))
        self._lock = RLock()

    @property
    def root(self) -> Path:
        return self._root

    def observe(self, proposal: PatchProposal) -> tuple[WorkspaceFileState, ...]:
        if not isinstance(proposal, PatchProposal):
            raise TypeError("proposal must be a PatchProposal")
        with self._lock:
            return tuple(self._snapshot(self._root, path).state for path in proposal.touched_paths)

    def execute(self, request: PatchExecutionRequest) -> PatchExecutionRecord:
        if not isinstance(request, PatchExecutionRequest):
            raise TypeError("request must be a PatchExecutionRequest")
        evidence: list[ToolEvidence] = []
        artifact: PatchArtifact | None = None
        with self._lock:
            sandbox = Path(tempfile.mkdtemp(prefix="dor-patch-sandbox-", dir=str(self._root.parent)))
            try:
                self._copy_workspace(sandbox)
                self._apply_in_sandbox(sandbox, request.proposal.unified_diff)
                artifact = self._artifact_from(sandbox, request)
                for tool in request.tools:
                    raw = self._tool_runner.run(tool, cwd=sandbox)
                    item = _tool_evidence(tool, artifact.artifact_id, raw)
                    evidence.append(item)
                    if not item.passed:
                        return self._failed(request, artifact, tuple(evidence), f"trusted {tool.kind.value} tool {tool.tool_id!r} finished with status {item.status.value}")
                after_tools = self._artifact_from(sandbox, request)
                if after_tools.artifact_id != artifact.artifact_id:
                    return self._failed(request, after_tools, tuple(evidence), "trusted tools modified one or more approved patch paths")
                self._require_live_baseline(request)
                self._commit_candidate(request, sandbox, artifact)
                return PatchExecutionRecord(request_fingerprint=request.request_fingerprint, proposal_id=request.proposal.proposal_id, baseline_fingerprint=request.baseline_fingerprint, status=PatchRecordStatus.SUCCEEDED, artifact=artifact, evidence=tuple(evidence), committed=True, rolled_back=False)
            except (PatchExecutionContractError, PatchWorkspaceError, OSError, subprocess.SubprocessError) as exc:
                return self._failed(request, artifact, tuple(evidence), f"{type(exc).__name__}: {exc}")
            finally:
                shutil.rmtree(sandbox, ignore_errors=True)

    def _failed(self, request: PatchExecutionRequest, artifact: PatchArtifact | None, evidence: tuple[ToolEvidence, ...], error: str) -> PatchExecutionRecord:
        return PatchExecutionRecord(request_fingerprint=request.request_fingerprint, proposal_id=request.proposal.proposal_id, baseline_fingerprint=request.baseline_fingerprint, status=PatchRecordStatus.FAILED, artifact=artifact, evidence=evidence, committed=False, rolled_back=True, error=error)

    def _require_live_baseline(self, request: PatchExecutionRequest) -> None:
        observed = tuple(self._snapshot(self._root, path).state for path in request.proposal.touched_paths)
        if observed != request.baseline:
            raise PatchWorkspaceError("live workspace no longer matches the authority-bound baseline")

    def _copy_workspace(self, destination: Path) -> None:
        file_count = 0
        byte_count = 0
        for current, directory_names, file_names in os.walk(self._root, topdown=True, followlinks=False):
            current_path = Path(current)
            relative = current_path.relative_to(self._root)
            kept_directories: list[str] = []
            for name in sorted(directory_names):
                source = current_path / name
                if name in _EXCLUDED_DIRECTORY_NAMES:
                    continue
                info = source.lstat()
                if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):
                    raise PatchWorkspaceError(f"unsafe workspace directory: {(relative / name).as_posix()}")
                kept_directories.append(name)
            directory_names[:] = kept_directories
            target_directory = destination / relative
            target_directory.mkdir(parents=True, exist_ok=True)
            for name in sorted(file_names):
                if _excluded_file(name):
                    continue
                source = current_path / name
                info = source.lstat()
                relative_file = relative / name
                if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode):
                    raise PatchWorkspaceError(f"unsafe workspace file: {relative_file.as_posix()}")
                if info.st_size > self._max_file_bytes:
                    raise PatchWorkspaceError(f"workspace file exceeds max_file_bytes: {relative_file.as_posix()}")
                file_count += 1
                byte_count += info.st_size
                if file_count > self._max_workspace_files or byte_count > self._max_workspace_bytes:
                    raise PatchWorkspaceError("workspace exceeds configured copy limits")
                shutil.copy2(source, target_directory / name, follow_symlinks=False)

    def _apply_in_sandbox(self, sandbox: Path, unified_diff: str) -> None:
        payload = unified_diff.encode("utf-8")
        environment = {"PATH": os.defpath, "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull, "LC_ALL": "C.UTF-8", "LANG": "C.UTF-8"}
        for check_only in (True, False):
            if _file_sha256(Path(self._git)) != self._git_sha256:
                raise PatchWorkspaceError("the fixed Git patch executable changed after configuration")
            arguments = [self._git, "apply", "--whitespace=nowarn"]
            if check_only:
                arguments.append("--check")
            arguments.append("-")
            completed = subprocess.run(tuple(arguments), cwd=sandbox, env=environment, input=payload, capture_output=True, timeout=self._patch_timeout_seconds, check=False, shell=False)
            if completed.returncode != 0:
                detail = completed.stderr[:4096].decode("utf-8", errors="replace").strip()
                phase = "validation" if check_only else "application"
                raise PatchWorkspaceError(f"patch {phase} failed: {detail or 'git apply rejected the patch'}")

    def _artifact_from(self, root: Path, request: PatchExecutionRequest) -> PatchArtifact:
        states = tuple(self._snapshot(root, path).state for path in request.proposal.touched_paths)
        return PatchArtifact(proposal_id=request.proposal.proposal_id, diff_sha256=request.proposal.diff_sha256, baseline_fingerprint=request.baseline_fingerprint, files=states)

    def _snapshot(self, root: Path, path: str) -> _FileSnapshot:
        validate_repository_path(path)
        target = root / path
        try:
            info = target.lstat()
        except FileNotFoundError:
            return _FileSnapshot(WorkspaceFileState(path, False, None, 0, None), None)
        if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode):
            raise PatchWorkspaceError(f"workspace path is not a regular file: {path}")
        content = target.read_bytes()
        if len(content) > self._max_file_bytes:
            raise PatchWorkspaceError(f"approved path exceeds max_file_bytes: {path}")
        return _FileSnapshot(WorkspaceFileState(path, True, hashlib.sha256(content).hexdigest(), len(content), stat.S_IMODE(info.st_mode)), content)

    def _commit_candidate(self, request: PatchExecutionRequest, sandbox: Path, artifact: PatchArtifact) -> None:
        rollback: list[tuple[Path, bytes | None, int | None]] = []
        try:
            for path in request.proposal.touched_paths:
                source = sandbox / path
                target = self._root / path
                before = self._snapshot(self._root, path)
                rollback.append((target, before.content, before.state.mode))
                target.parent.mkdir(parents=True, exist_ok=True)
                if source.exists():
                    shutil.copy2(source, target, follow_symlinks=False)
                elif target.exists():
                    target.unlink()
        except Exception:
            for target, content, mode in reversed(rollback):
                if content is None:
                    target.unlink(missing_ok=True)
                else:
                    target.write_bytes(content)
                    if mode is not None:
                        os.chmod(target, mode)
            raise


class PatchExecutionAdapter:
    """AI-4 adapter that executes only operator-registered immutable requests."""

    def __init__(self, *, adapter_id: str, workspace: WorkspacePatchExecutor) -> None:
        if not isinstance(adapter_id, str) or not adapter_id.strip():
            raise ValueError("adapter_id must be a non-empty string")
        if not isinstance(workspace, WorkspacePatchExecutor):
            raise TypeError("workspace must be a WorkspacePatchExecutor")
        self._adapter_id = adapter_id
        self._workspace = workspace
        self._requests: dict[str, PatchExecutionRequest] = {}
        self._records: dict[str, PatchExecutionRecord] = {}
        self._lock = RLock()

    @property
    def adapter_id(self) -> str:
        return self._adapter_id

    @property
    def action(self) -> str:
        return IMPLEMENTATION_APPLY_ACTION

    @property
    def workspace(self) -> WorkspacePatchExecutor:
        return self._workspace

    def register_request(self, request: PatchExecutionRequest) -> None:
        if not isinstance(request, PatchExecutionRequest):
            raise TypeError("request must be a PatchExecutionRequest")
        with self._lock:
            existing = self._requests.get(request.request_fingerprint)
            if existing is not None and existing != request:
                raise PatchExecutionContractError("patch request fingerprint collision or rebinding")
            self._requests[request.request_fingerprint] = request

    def execute(self, request: ExecutionRequest) -> AdapterResult:
        if not isinstance(request, ExecutionRequest):
            raise TypeError("request must be an ExecutionRequest")
        fingerprint = dict(request.parameters).get("patch_execution_request_fingerprint")
        if fingerprint is None:
            raise PatchExecutionRequestBindingError("execution request is missing the patch request fingerprint")
        with self._lock:
            registered = self._requests.get(fingerprint)
            if registered is None:
                raise PatchExecutionRequestNotFoundError(fingerprint)
            expected = registered.execution_request(idempotency_key=request.idempotency_key)
            for name in ("request_id", "agent_identity", "action", "resource", "context_packet_id", "parameters"):
                if getattr(request, name) != getattr(expected, name):
                    raise PatchExecutionRequestBindingError(f"execution {name} does not match the registered patch request")
            existing = self._records.get(fingerprint)
            if existing is not None:
                if existing.status is PatchRecordStatus.FAILED:
                    raise PatchExecutionFailed(existing)
                return _adapter_result(existing)
            record = self._workspace.execute(registered)
            self._records[fingerprint] = record
            if record.status is PatchRecordStatus.FAILED:
                raise PatchExecutionFailed(record)
            return _adapter_result(record)

    def get_record(self, request_fingerprint: str) -> PatchExecutionRecord:
        with self._lock:
            try:
                return self._records[request_fingerprint]
            except KeyError as exc:
                raise PatchExecutionRequestNotFoundError(request_fingerprint) from exc


def canonical_python_tools(*, timeout_seconds: int = 300, max_output_bytes: int = 256 * 1024) -> tuple[TrustedToolSpec, ...]:
    executable = os.path.abspath(sys.executable)
    sandbox_environment = (("DOR_JWT_SECRET_KEY", secrets.token_urlsafe(32)),)
    return (
        TrustedToolSpec("python.ruff", ToolKind.LINT, (executable, "-m", "ruff", "check", "--isolated", "--select", "E9,F63,F7", "."), timeout_seconds, max_output_bytes, sandbox_environment),
        TrustedToolSpec("python.pytest", ToolKind.TEST, (executable, "-m", "pytest", "-q"), timeout_seconds, max_output_bytes, sandbox_environment),
        TrustedToolSpec("python.compileall", ToolKind.BUILD, (executable, "-m", "compileall", "-q", "."), timeout_seconds, max_output_bytes, sandbox_environment),
    )


def _adapter_result(record: PatchExecutionRecord) -> AdapterResult:
    if record.artifact is None:
        raise PatchExecutionAdapterError("successful patch record has no artifact")
    return AdapterResult(output=(("artifact_id", record.artifact.artifact_id), ("baseline_fingerprint", record.baseline_fingerprint), ("evidence_ids", ",".join(item.evidence_id for item in record.evidence)), ("patch_execution_record_id", record.record_id), ("proposal_id", record.proposal_id)))


def _tool_evidence(tool: TrustedToolSpec, artifact_id: str, result: RawToolResult) -> ToolEvidence:
    return ToolEvidence(tool_id=tool.tool_id, kind=tool.kind, tool_fingerprint=tool.tool_fingerprint, artifact_id=artifact_id, status=result.status, exit_code=result.exit_code, stdout=_log_artifact("stdout", result.stdout, tool.max_output_bytes), stderr=_log_artifact("stderr", result.stderr, tool.max_output_bytes))


def _log_artifact(stream: str, content: bytes, limit: int) -> LogArtifact:
    preview = content[:limit]
    return LogArtifact(stream=stream, sha256=hashlib.sha256(content).hexdigest(), byte_count=len(content), content=preview.decode("utf-8", errors="replace"), truncated=len(content) > limit)


def _as_bytes(value: bytes | str | None) -> bytes:
    if value is None:
        return b""
    if isinstance(value, bytes):
        return value
    return value.encode("utf-8", errors="replace")


def _validated_root(root: Path) -> Path:
    if not isinstance(root, Path):
        raise TypeError("workspace root must be a pathlib.Path")
    absolute = Path(os.path.abspath(root))
    try:
        resolved = root.resolve(strict=True)
    except OSError as exc:
        raise PatchWorkspaceError("workspace root must be an existing directory") from exc
    if absolute != resolved:
        raise PatchWorkspaceError("workspace root cannot contain symlink components")
    if not resolved.is_dir():
        raise PatchWorkspaceError("workspace root must be a directory")
    return resolved


def _excluded_file(name: str) -> bool:
    return name in _EXCLUDED_FILE_NAMES or name.endswith(_EXCLUDED_FILE_SUFFIXES)


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
