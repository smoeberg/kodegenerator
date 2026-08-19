"""OS-isolated execution boundary for untrusted generated Python code.

All generated-code subprocesses must enter through :class:`BubblewrapSandbox`.
The sandbox is fail-closed when bwrap is unavailable, has no network namespace,
and exposes only an explicit read-only project view plus a private writable
workspace.
"""
from __future__ import annotations

import os
import resource
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence


class SandboxError(RuntimeError):
    """Base sandbox failure."""


class SandboxUnavailableError(SandboxError):
    """The required Bubblewrap runtime is unavailable."""


@dataclass(frozen=True)
class SandboxLimits:
    timeout_seconds: float = 30.0
    memory_bytes: int = 512 * 1024 * 1024
    cpu_seconds: int = 20
    max_processes: int = 32

    def __post_init__(self) -> None:
        if self.timeout_seconds <= 0 or self.cpu_seconds <= 0:
            raise ValueError("sandbox time limits must be positive")
        if self.memory_bytes < 16 * 1024 * 1024:
            raise ValueError("memory limit is unrealistically small")
        if self.max_processes < 1:
            raise ValueError("max_processes must be positive")


def _set_limits(limits: SandboxLimits) -> None:
    resource.setrlimit(resource.RLIMIT_CPU, (limits.cpu_seconds, limits.cpu_seconds))
    resource.setrlimit(resource.RLIMIT_AS, (limits.memory_bytes, limits.memory_bytes))
    resource.setrlimit(resource.RLIMIT_NPROC, (limits.max_processes, limits.max_processes))
    resource.setrlimit(resource.RLIMIT_NOFILE, (256, 256))


class BubblewrapSandbox:
    def __init__(self, project_root: Path, *, limits: SandboxLimits | None = None) -> None:
        self.project_root = Path(project_root).resolve()
        self.limits = limits or SandboxLimits()
        self.bwrap = shutil.which("bwrap")
        if self.bwrap is None:
            raise SandboxUnavailableError("Bubblewrap (bwrap) is required for generated-code execution")
        if not self.project_root.is_dir():
            raise SandboxError("sandbox project root must be a directory")

    def command(self, argv: Sequence[str], workspace: Path) -> list[str]:
        workspace = Path(workspace).resolve()
        workspace.mkdir(parents=True, exist_ok=True)
        if self.project_root == workspace or self.project_root in workspace.parents:
            raise SandboxError("workspace must not be inside the project root")
        return [
            self.bwrap,
            "--die-with-parent",
            "--new-session",
            "--unshare-all",
            "--clearenv",
            "--ro-bind", "/", "/",
            "--dev", "/dev",
            "--proc", "/proc",
            "--tmpfs", "/tmp",
            "--dir", "/workspace",
            "--ro-bind", str(self.project_root), "/project",
            "--bind", str(workspace), "/workspace",
            "--chdir", "/workspace",
            "--setenv", "HOME", "/workspace",
            "--setenv", "PYTHONDONTWRITEBYTECODE", "1",
            "--setenv", "PYTHONNOUSERSITE", "1",
            "--", *map(str, argv),
        ]

    def run(self, argv: Sequence[str], workspace: Path) -> subprocess.CompletedProcess[str]:
        env = {"PATH": os.environ.get("PATH", "/usr/local/bin:/usr/bin:/bin")}
        command = self.command(argv, workspace)
        try:
            return subprocess.run(
                command,
                cwd=str(workspace),
                env=env,
                text=True,
                capture_output=True,
                timeout=self.limits.timeout_seconds,
                preexec_fn=lambda: _set_limits(self.limits),
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise SandboxError("sandbox execution exceeded wall-clock limit") from exc
