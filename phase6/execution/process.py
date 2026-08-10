"""Concrete process isolation backend for Phase 6.

The adapter uses bubblewrap (``bwrap``) to create Linux namespaces and a
read-only host filesystem view. It fails closed when the isolation primitive
is unavailable instead of silently falling back to an ordinary subprocess.

Resource limits are applied to the sandbox launcher and inherited by the
sandboxed process. Network access is denied by the isolated network namespace;
this backend intentionally does not support network allowlists yet.
"""
from __future__ import annotations

import os
import resource
import shutil
import subprocess
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


class BubblewrapProcessAdapter:
    """Run an allowlisted executable inside a bubblewrap process sandbox.

    The adapter is deliberately narrow: network access is always disabled and
    the executable must be explicitly allowlisted when the adapter is created.
    """

    adapter_id = "bubblewrap-process"

    def __init__(
        self,
        *,
        allowed_executables: Sequence[str],
        bubblewrap_path: str | None = None,
        runner: Callable[..., subprocess.Popen[str]] = subprocess.Popen,
    ) -> None:
        candidate = bubblewrap_path or shutil.which("bwrap")
        if not candidate or not os.path.isfile(candidate) or not os.access(candidate, os.X_OK):
            raise ProcessSandboxUnavailable("bubblewrap (bwrap) is required for process isolation")
        if not allowed_executables:
            raise ValueError("at least one executable must be allowlisted")
        self._bubblewrap = str(Path(candidate).resolve())
        self._allowed = frozenset(str(Path(value).resolve()) for value in allowed_executables)
        self._runner = runner

    def execute(self, spec: ExecutionSpec) -> ExecutionResult:
        self._validate_spec(spec)
        command = self._build_command(spec)
        limits = _ProcessLimits(
            cpu_seconds=max(1, int(spec.limits.cpu_time_seconds)),
            memory_bytes=spec.limits.memory_bytes,
            process_count=max(2, spec.limits.process_count),
        )

        try:
            process = self._runner(
                command,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                env=self._safe_environment(spec),
                start_new_session=True,
                preexec_fn=lambda: _apply_limits(limits),
            )
            try:
                output, _ = process.communicate(timeout=spec.limits.wall_time_seconds)
            except subprocess.TimeoutExpired:
                process.kill()
                output, _ = process.communicate()
                return ExecutionResult(
                    execution_id=spec.execution_id,
                    adapter_id=self.adapter_id,
                    outcome=ExecutionOutcome.TIMED_OUT,
                    output=_bound_output(output, spec.limits.output_bytes),
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

        bounded = _bound_output(output, spec.limits.output_bytes)
        if len(output.encode("utf-8")) > spec.limits.output_bytes:
            return ExecutionResult(
                execution_id=spec.execution_id,
                adapter_id=self.adapter_id,
                outcome=ExecutionOutcome.FAILED,
                output=bounded,
                error="execution output exceeded configured limit",
                exit_code=process.returncode,
            )

        if process.returncode == 0:
            return ExecutionResult(
                execution_id=spec.execution_id,
                adapter_id=self.adapter_id,
                outcome=ExecutionOutcome.SUCCEEDED,
                output=bounded,
                exit_code=0,
            )
        return ExecutionResult(
            execution_id=spec.execution_id,
            adapter_id=self.adapter_id,
            outcome=ExecutionOutcome.FAILED,
            output=bounded,
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
            self._bubblewrap,
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
            "--tmpfs",
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


def _bound_output(output: str, limit: int) -> str:
    encoded = output.encode("utf-8")
    if len(encoded) <= limit:
        return output
    return encoded[:limit].decode("utf-8", errors="ignore")
