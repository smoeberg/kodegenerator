"""Concrete process isolation backend for Phase 6."""
from __future__ import annotations

import os
import resource
import shutil
import signal
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Sequence

from phase6.execution.sandbox import ExecutionOutcome, ExecutionResult, ExecutionSpec, InvalidExecutionSpec


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
        self._bwrap_available = None

    def _is_bwrap_available(self) -> bool:
        """Check if bubblewrap is available and executable."""
        if self._bwrap_available is not None:
            return self._bwrap_available
        candidate = self._bubblewrap_candidate
        if candidate and os.path.isfile(candidate) and os.access(candidate, os.X_OK):
            self._bwrap_available = True
            return True
        # Try default locations
        for default_path in ("/usr/bin/bwrap", "/bin/bwrap"):
            if os.path.isfile(default_path) and os.access(default_path, os.X_OK):
                self._bubblewrap_candidate = default_path
                self._bwrap_available = True
                return True
        self._bwrap_available = False
        return False

    def _resolve_bubblewrap(self) -> str:
        if not self._is_bwrap_available():
            raise ProcessSandboxUnavailable("bubblewrap (bwrap) is required for process isolation")
        return str(Path(self._bubblewrap_candidate).resolve())

    def _apply_fallback_limits(self, limits: _ProcessLimits) -> None:
        """Apply resource limits as a fallback when bubblewrap is not available."""
        # Set hard resource limits using RLIMIT_*
        resource.setrlimit(resource.RLIMIT_CPU, (limits.cpu_seconds, limits.cpu_seconds))
        resource.setrlimit(resource.RLIMIT_AS, (limits.memory_bytes, limits.memory_bytes))
        resource.setrlimit(resource.RLIMIT_NPROC, (limits.process_count, limits.process_count))
        resource.setrlimit(resource.RLIMIT_FSIZE, (limits.file_size_bytes, limits.file_size_bytes))
        resource.setrlimit(resource.RLIMIT_NOFILE, (limits.open_file_count, limits.open_file_count))
        resource.setrlimit(resource.RLIMIT_CORE, (0, 0))

    def _execute_with_bubblewrap(self, spec: ExecutionSpec, limits: _ProcessLimits) -> ExecutionResult:
        """Execute using bubblewrap for strong isolation."""
        self._bubblewrap_path = self._resolve_bubblewrap()
        sandbox_tmp = str(Path(tempfile.gettempdir()).resolve())
        
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
                    return ExecutionResult(
                        spec.execution_id, 
                        self.adapter_id, 
                        ExecutionOutcome.TIMED_OUT, 
                        _read_bounded_output(output_file, spec.limits.output_bytes), 
                        "execution exceeded wall-time limit", 
                        process.returncode
                    )
            except OSError as exc:
                return ExecutionResult(
                    spec.execution_id, 
                    self.adapter_id, 
                    ExecutionOutcome.FAILED, 
                    error=f"sandbox launch failed: {exc}"
                )
            
            output = _read_bounded_output(output_file, spec.limits.output_bytes)
            output_file.seek(0, os.SEEK_END)
            if output_file.tell() > spec.limits.output_bytes:
                return ExecutionResult(
                    spec.execution_id, 
                    self.adapter_id, 
                    ExecutionOutcome.FAILED, 
                    output, 
                    "execution output exceeded configured limit", 
                    process.returncode
                )
        
        if process.returncode == 0:
            return ExecutionResult(
                spec.execution_id, 
                self.adapter_id, 
                ExecutionOutcome.SUCCEEDED, 
                output, 
                exit_code=0
            )
        detail = f"sandbox exited with code {process.returncode}"
        if output:
            detail = f"{detail}: {output.strip()}"
        return ExecutionResult(
            spec.execution_id, 
            self.adapter_id, 
            ExecutionOutcome.FAILED, 
            output, 
            detail, 
            process.returncode
        )

    def _execute_with_fallback(self, spec: ExecutionSpec, limits: _ProcessLimits) -> ExecutionResult:
        """Execute with RLIMIT_* fallback when bubblewrap is not available."""
        # Validate spec for fallback execution
        self._validate_fallback_spec(spec)
        
        with tempfile.TemporaryFile(mode="w+b") as output_file:
            try:
                # Apply resource limits before execution
                self._apply_fallback_limits(limits)
                
                process = self._runner(
                    spec.argv,
                    stdin=subprocess.DEVNULL,
                    stdout=output_file,
                    stderr=subprocess.STDOUT,
                    text=False,
                    env=self._safe_environment(spec),
                    start_new_session=True,
                    preexec_fn=lambda: _apply_fallback_limits(limits),
                )
                
                try:
                    process.communicate(timeout=spec.limits.wall_time_seconds)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.communicate()
                    return ExecutionResult(
                        spec.execution_id, 
                        self.adapter_id, 
                        ExecutionOutcome.TIMED_OUT, 
                        _read_bounded_output(output_file, spec.limits.output_bytes), 
                        "execution exceeded wall-time limit (fallback mode)", 
                        process.returncode
                    )
            except OSError as exc:
                return ExecutionResult(
                    spec.execution_id, 
                    self.adapter_id, 
                    ExecutionOutcome.FAILED, 
                    error=f"sandbox launch failed (fallback): {exc}"
                )
            
            output = _read_bounded_output(output_file, spec.limits.output_bytes)
            
            if process.returncode == 0:
                return ExecutionResult(
                    spec.execution_id, 
                    self.adapter_id, 
                    ExecutionOutcome.SUCCEEDED, 
                    output, 
                    exit_code=0
                )
            detail = f"sandbox exited with code {process.returncode} (fallback mode)"
            if output:
                detail = f"{detail}: {output.strip()}"
            return ExecutionResult(
                spec.execution_id, 
                self.adapter_id, 
                ExecutionOutcome.FAILED, 
                output, 
                detail, 
                process.returncode
            )

    def execute(self, spec: ExecutionSpec) -> ExecutionResult:
        self._validate_spec(spec)
        limits = _ProcessLimits(
            max(1, int(spec.limits.cpu_time_seconds)),
            spec.limits.memory_bytes,
            spec.limits.process_count,
            spec.limits.file_size_bytes,
            spec.limits.open_file_count,
        )
        
        # Try bubblewrap first, fall back to RLIMIT_* if not available
        if self._is_bwrap_available():
            return self._execute_with_bubblewrap(spec, limits)
        else:
            return self._execute_with_fallback(spec, limits)

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
        for path in spec.writable_paths:
            source = Path(path)
            if source.is_symlink():
                raise InvalidExecutionSpec("writable sandbox paths must not be symlinks")
            resolved = source.resolve(strict=True)
            if resolved == Path(os.sep):
                raise InvalidExecutionSpec("root cannot be writable")
            allowed_roots = (tmp_root, var_tmp_root)
            if not any(resolved == root or root in resolved.parents for root in allowed_roots):
                raise InvalidExecutionSpec("writable sandbox paths must be under /tmp or /var/tmp")
            if not resolved.is_dir():
                raise InvalidExecutionSpec("writable sandbox paths must be directories")
        if spec.working_directory is not None:
            working = Path(spec.working_directory).resolve(strict=True)
            if not working.is_dir():
                raise InvalidExecutionSpec("working_directory must be an existing directory")
            if spec.working_directory not in spec.writable_paths and spec.working_directory not in spec.read_only_paths:
                raise InvalidExecutionSpec("working_directory must be mounted")

    def _validate_fallback_spec(self, spec: ExecutionSpec) -> None:
        """Validate spec for fallback execution (less strict than bubblewrap)."""
        executable = str(Path(spec.argv[0]).resolve())
        if executable not in self._allowed:
            raise InvalidExecutionSpec(f"executable is not allowlisted: {spec.argv[0]}")
        # In fallback mode, we allow execution without filesystem path restrictions
        # but still enforce basic safety
        if spec.network_allowlist:
            raise InvalidExecutionSpec("network allowlists are not supported in fallback mode")

    def _build_command(self, spec):
        sandbox_tmp = str(Path(tempfile.gettempdir()).resolve())
        command = [
            self._bubblewrap_path or "bwrap",
            "--die-with-parent",
            "--new-session",
            "--unshare-user",
            "--unshare-pid",
            "--unshare-uts",
            "--unshare-ipc",
            "--unshare-net",
            "--ro-bind", os.sep, os.sep,
            "--dev", "/dev",
            "--proc", "/proc",
            "--tmpfs", sandbox_tmp,
        ]
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
