"""Concrete process isolation backend for Phase 6."""
from __future__ import annotations

import os
import resource
import shutil
import subprocess
import tempfile
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

from phase6.execution.sandbox import (
    ExecutionOutcome,
    ExecutionResult,
    ExecutionSpec,
    InvalidExecutionSpec,
)


class ProcessSandboxUnavailable(RuntimeError):
    pass


@dataclass(frozen=True)
class _ProcessLimits:
    cpu_seconds: int
    memory_bytes: int
    process_count: int
    file_size_bytes: int
    open_file_count: int


class BubblewrapProcessAdapter:
    adapter_id = "bubblewrap-process"

    def __init__(self, *, allowed_executables: Sequence[str], bubblewrap_path: str | None = None, runner: Callable[..., subprocess.Popen[str]] = subprocess.Popen):
        if not allowed_executables:
            raise ValueError("at least one executable must be allowlisted")
        self._bubblewrap_candidate = bubblewrap_path or shutil.which("bwrap")
        self._bubblewrap_path = None
        self._allowed = frozenset(str(Path(v).resolve()) for v in allowed_executables)
        self._runner = runner

    def _resolve_bubblewrap(self):
        candidate = self._bubblewrap_candidate
        if not candidate or not os.path.isfile(candidate) or not os.access(candidate, os.X_OK):
            raise ProcessSandboxUnavailable("bubblewrap (bwrap) is required for process isolation")
        return str(Path(candidate).resolve())

    def execute(self, spec: ExecutionSpec) -> ExecutionResult:
        self._validate_spec(spec)
        self._bubblewrap_path = self._resolve_bubblewrap()
        limits = _ProcessLimits(
            max(1, int(spec.limits.cpu_time_seconds)),
            spec.limits.memory_bytes,
            spec.limits.process_count,
            spec.limits.file_size_bytes,
            spec.limits.open_file_count,
        )
        with tempfile.TemporaryFile(mode="w+b") as output_file:
            try:
                process = self._runner(
                    self._build_command(spec),
                    stdin=subprocess.DEVNULL,
                    stdout=output_file,
                    stderr=subprocess.STDOUT,
                    text=False,
                    env=self._safe_environment(spec),
                    start_new_session=True,
                    preexec_fn=lambda: _apply_launcher_limits(limits),
                )
                try:
                    process.communicate(timeout=spec.limits.wall_time_seconds)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.communicate()
                    return ExecutionResult(spec.execution_id, self.adapter_id, ExecutionOutcome.TIMED_OUT, _read_bounded_output(output_file, spec.limits.output_bytes), "execution exceeded wall-time limit", process.returncode)
            except OSError as exc:
                return ExecutionResult(spec.execution_id, self.adapter_id, ExecutionOutcome.FAILED, error=f"sandbox launch failed: {exc}")
            output = _read_bounded_output(output_file, spec.limits.output_bytes)
            output_file.seek(0, os.SEEK_END)
            if output_file.tell() > spec.limits.output_bytes:
                return ExecutionResult(spec.execution_id, self.adapter_id, ExecutionOutcome.FAILED, output, "execution output exceeded configured limit", process.returncode)
        if process.returncode == 0:
            return ExecutionResult(spec.execution_id, self.adapter_id, ExecutionOutcome.SUCCEEDED, output, exit_code=0)
        detail = f"sandbox exited with code {process.returncode}"
        if output:
            detail = f"{detail}: {output.strip()}"
        return ExecutionResult(spec.execution_id, self.adapter_id, ExecutionOutcome.FAILED, output, detail, process.returncode)

    def _validate_spec(self, spec):
        executable = str(Path(spec.argv[0]).resolve())
        if executable not in self._allowed:
            raise InvalidExecutionSpec(f"executable is not allowlisted: {spec.argv[0]}")
        if spec.network_allowlist:
            raise InvalidExecutionSpec("network allowlists are not supported by the isolated process backend")
        for path in (*spec.read_only_paths, *spec.writable_paths):
            if not os.path.isabs(path):
                raise InvalidExecutionSpec("sandbox filesystem paths must be absolute")
            if not os.path.exists(path):
                raise InvalidExecutionSpec(f"sandbox filesystem path does not exist: {path}")
        tmp_root = Path(tempfile.gettempdir()).resolve()
        var_tmp_root = (Path(os.sep) / "var" / "tmp").resolve()
        allowed_data_roots = (tmp_root, var_tmp_root)
        for path in spec.read_only_paths:
            resolved = Path(path).resolve(strict=True)
            if not any(resolved == root or root in resolved.parents for root in allowed_data_roots):
                raise InvalidExecutionSpec("read-only sandbox data paths must be under /tmp or /var/tmp")
        for path in spec.writable_paths:
            source = Path(path)
            if source.is_symlink():
                raise InvalidExecutionSpec("writable sandbox paths must not be symlinks")
            resolved = source.resolve(strict=True)
            if resolved == Path(os.sep):
                raise InvalidExecutionSpec("root cannot be writable")
            if not any(resolved == root or root in resolved.parents for root in allowed_data_roots):
                raise InvalidExecutionSpec("writable sandbox paths must be under /tmp or /var/tmp")
            if not resolved.is_dir():
                raise InvalidExecutionSpec("writable sandbox paths must be directories")
        if spec.working_directory is not None:
            working = Path(spec.working_directory).resolve(strict=True)
            if not working.is_dir():
                raise InvalidExecutionSpec("working_directory must be an existing directory")
            if spec.working_directory not in spec.writable_paths and spec.working_directory not in spec.read_only_paths:
                raise InvalidExecutionSpec("working_directory must be mounted")

    def _build_command(self, spec):
        command = [
            self._bubblewrap_path or "bwrap",
            "--die-with-parent",
            "--new-session",
            "--unshare-user",
            "--unshare-pid",
            "--unshare-uts",
            "--unshare-ipc",
            "--unshare-net",
            "--tmpfs", os.sep,
            "--dev", "/dev",
            "--proc", "/proc",
            "--tmpfs", "/tmp",
        ]
        # Build an empty root and expose only the runtime needed to launch
        # allowlisted executables.  In particular, never inherit /etc, /app,
        # user homes, or arbitrary host paths through a root bind.
        for system_path in ("/usr", "/lib", "/lib64", "/bin"):
            if os.path.exists(system_path):
                command.extend(("--ro-bind", system_path, system_path))
        for blocked_path in ("/app", "/etc", "/home", "/root"):
            command.extend(("--dir", blocked_path))
        for path in spec.writable_paths:
            target = str(Path(path).resolve())
            command.extend(("--dir", target))
        for path in spec.read_only_paths:
            target = str(Path(path).resolve())
            command.extend(("--ro-bind", target, target))
        for path in spec.writable_paths:
            target = str(Path(path).resolve())
            command.extend(("--bind", target, target))
        command.extend(("--chdir", spec.working_directory or os.sep, "--", *spec.argv))
        return command

    @staticmethod
    def _safe_environment(spec):
        return {"PATH": "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin", "LANG": "C.UTF-8", "PYTHONNOUSERSITE": "1", "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1", **dict(spec.environment)}


def _apply_limits(limits):
    """Apply the exact hard limits requested by the execution contract."""
    resource.setrlimit(resource.RLIMIT_CPU, (limits.cpu_seconds, limits.cpu_seconds))
    resource.setrlimit(resource.RLIMIT_AS, (limits.memory_bytes, limits.memory_bytes))
    resource.setrlimit(resource.RLIMIT_NPROC, (limits.process_count, limits.process_count))
    resource.setrlimit(resource.RLIMIT_FSIZE, (limits.file_size_bytes, limits.file_size_bytes))
    resource.setrlimit(resource.RLIMIT_NOFILE, (limits.open_file_count, limits.open_file_count))
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))


def _apply_launcher_limits(limits):
    """Apply host-side limits without constraining bubblewrap or its runtime mappings."""
    resource.setrlimit(resource.RLIMIT_CPU, (limits.cpu_seconds, limits.cpu_seconds))
    resource.setrlimit(resource.RLIMIT_FSIZE, (limits.file_size_bytes, limits.file_size_bytes))
    resource.setrlimit(resource.RLIMIT_NOFILE, (limits.open_file_count, limits.open_file_count))
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))


def _read_bounded_output(output_file, limit):
    output_file.seek(0)
    return output_file.read(limit + 1).decode("utf-8", errors="replace")[:limit]
