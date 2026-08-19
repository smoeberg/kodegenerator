"""Concrete process isolation backend for Phase 6.

The adapter uses bubblewrap (``bwrap``) to create Linux namespaces and a
read-only host filesystem view. It fails closed when the isolation primitive
is unavailable instead of silently falling back to an ordinary subprocess.

P6-04 makes resource limits hard limits: CPU, address space, process count,
file size, open descriptors, core dumps, wall-clock time, and captured output
are bounded. Output is captured to a file descriptor instead of an unbounded
PIPE buffer in the trusted parent process.
"""
from __future__ import annotations

import os
import resource
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Sequence

from phase6.execution.sandbox import (
    ExecutionOutcome,
    ExecutionResult,
    ExecutionSpec,
    InvalidExecutionSpec,
)


class ProcessSandboxUnavailable(RuntimeError):
    """Raised when the required Linux isolation primitive is unavailable."""


@dataclass(frozen=True)
class _ProcessLimits:
    cpu_seconds: int
    memory_bytes: int
    process_count: int
    file_size_bytes: int
    open_file_count: int


class BubblewrapProcessAdapter:
    """Run an allowlisted executable inside a bubblewrap process sandbox."""

    adapter_id = "bubblewrap-process"

    def __init__(
        self,
        *,
        allowed_executables: Sequence[str],
        bubblewrap_path: str | None = None,
        runner: Callable[..., subprocess.Popen[str]] = subprocess.Popen,
    ) -> None:
        if not allowed_executables:
            raise ValueError("at least one executable must be allowlisted")
        candidate = bubblewrap_path or shutil.which("bwrap")
        # bwrap availability is resolved lazily at execute() time so that spec
        # validation and command construction remain testable without the
        # isolation primitive installed. fail-closed is preserved: an
        # unavailable primitive rejects any execution before a process starts.
        self._bubblewrap_candidate = candidate
        self._bubblewrap_path: str | None = None
        self._allowed = frozenset(str(Path(value).resolve()) for value in allowed_executables)
        self._runner = runner

    def _resolve_bubblewrap(self) -> str:
        candidate = self._bubblewrap_candidate
        if not candidate or not os.path.isfile(candidate) or not os.access(candidate, os.X_OK):
            raise ProcessSandboxUnavailable("bubblewrap (bwrap) is required for process isolation")
        return str(Path(candidate).resolve())

    def execute(self, spec: ExecutionSpec) -> ExecutionResult:
        self._validate_spec(spec)
        self._bubblewrap_path = self._resolve_bubblewrap()
        command = self._build_command(spec)
        limits = _ProcessLimits(
            cpu_seconds=max(1, int(spec.limits.cpu_time_seconds)),
            memory_bytes=spec.limits.memory_bytes,
            process_count=spec.limits.process_count,
            file_size_bytes=spec.limits.file_size_bytes,
            open_file_count=spec.limits.open_file_count,
        )

        with tempfile.TemporaryFile(mode="w+b") as output_file:
            try:
                process = self._runner(
                    command,
                    stdin=subprocess.DEVNULL,
                    stdout=output_file,
                    stderr=subprocess.STDOUT,
                    text=False,
                    env=self._safe_environment(spec),
                    start_new_session=True,
                    preexec_fn=lambda: _apply_limits(limits),
                )
                try:
                    process.communicate(timeout=spec.limits.wall_time_seconds)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.communicate()
                    return ExecutionResult(
                        execution_id=spec.execution_id,
                        adapter_id=self.adapter_id,
                        outcome=ExecutionOutcome.TIMED_OUT,
                        output=_read_bounded_output(output_file, spec.limits.output_bytes),
                        error="execution exceeded wall-time limit",
                        exit_code=process.returncode,
                    )
            except OSError as exc:
                return ExecutionResult(
                    execution_id=spec.execution_id,
                    adapter_id=self.adapter_id,
                    outcome=ExecutionOutcome.FAILED,
                    error=f"sandbox launch failed: {exc}",
                )

            output = _read_bounded_output(output_file, spec.limits.output_bytes)
            output_file.seek(0, os.SEEK_END)
            output_size = output_file.tell()
            if output_size > spec.limits.output_bytes:
                return ExecutionResult(
                    execution_id=spec.execution_id,
                    adapter_id=self.adapter_id,
                    outcome=ExecutionOutcome.FAILED,
                    output=output,
                    error="execution output exceeded configured limit",
                    exit_code=process.returncode,
                )

        if process.returncode == 0:
            return ExecutionResult(
                execution_id=spec.execution_id,
                adapter_id=self.adapter_id,
                outcome=ExecutionOutcome.SUCCEEDED,
                output=output,
                exit_code=0,
            )
        return ExecutionResult(
            execution_id=spec.execution_id,
            adapter_id=self.adapter_id,
            outcome=ExecutionOutcome.FAILED,
            output=output,
            error=f"sandbox exited with code {process.returncode}",
            exit_code=process.returncode,
        )

    def _validate_spec(self, spec: ExecutionSpec) -> None:
        executable = str(Path(spec.argv[0]).resolve())
        if executable not in self._allowed:
            raise InvalidExecutionSpec(f"executable is not allowlisted: {spec.argv[0]}")
        if spec.network_allowlist:
            raise InvalidExecutionSpec("network allowlists are not supported by the isolated process backend")
        for path in (*spec.read_only_paths, *spec.writable_paths):
            if not os.path.isabs(path):
                raise InvalidExecutionSpec("sandbox filesystem paths must be absolute")
        for path in spec.writable_paths:
            if not os.path.exists(path):
                raise InvalidExecutionSpec(f"writable sandbox path does not exist: {path}")

    def _build_command(self, spec: ExecutionSpec) -> list[str]:
        command = [
            self._bubblewrap_path or "bwrap",
            "--die-with-parent",
            "--new-session",
            "--unshare-user",
            "--unshare-pid",
            "--unshare-uts",
            "--unshare-ipc",
            "--unshare-net",
            "--ro-bind",
            "/",
            "/",
            "--dev",
            "/dev",
            "--proc",
            "/proc",
            # Intentional private tmpfs: /tmp is the sandbox's ephemeral filesystem,
            # not a host temp directory. The suppression is scoped to this primitive.
            "--tmpfs",  # nosec B108 - bubblewrap creates an isolated in-sandbox tmpfs
            "/tmp",
        ]
        for path in spec.writable_paths:
            command.extend(("--bind", path, path))
        command.extend(("--chdir", "/", "--"))
        command.extend(spec.argv)
        return command

    @staticmethod
    def _safe_environment(spec: ExecutionSpec) -> dict[str, str]:
        return {
            "PATH": "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
            "LANG": "C.UTF-8",
            **dict(spec.environment),
        }


def _apply_limits(limits: _ProcessLimits) -> None:
    resource.setrlimit(resource.RLIMIT_CPU, (limits.cpu_seconds, limits.cpu_seconds))
    resource.setrlimit(resource.RLIMIT_AS, (limits.memory_bytes, limits.memory_bytes))
    resource.setrlimit(resource.RLIMIT_NPROC, (limits.process_count, limits.process_count))
    resource.setrlimit(resource.RLIMIT_FSIZE, (limits.file_size_bytes, limits.file_size_bytes))
    resource.setrlimit(resource.RLIMIT_NOFILE, (limits.open_file_count, limits.open_file_count))
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))


def _read_bounded_output(output_file, limit: int) -> str:
    output_file.seek(0)
    data = output_file.read(limit + 1)
    return data[:limit].decode("utf-8", errors="replace")
