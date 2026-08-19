"""Bridge trusted Phase 4 patch tools into the Phase 6 OS sandbox."""
from __future__ import annotations

import hashlib
from pathlib import Path

from phase6.execution.process import BubblewrapProcessAdapter, ProcessSandboxUnavailable
from phase6.execution.sandbox import ExecutionLimits, ExecutionSecurityContext, ExecutionSpec

from .patch_adapter import RawToolResult, ToolRunner
from .patch_models import ToolStatus, TrustedToolSpec


class BubblewrapToolRunner:
    """Execute operator-fixed patch tools only through the Phase 6 sandbox."""

    def __init__(self, *, bubblewrap_path: str | None = None) -> None:
        self._bubblewrap_path = bubblewrap_path

    def run(self, tool: TrustedToolSpec, *, cwd: Path) -> RawToolResult:
        if not isinstance(tool, TrustedToolSpec):
            raise TypeError("tool must be a TrustedToolSpec")
        if not isinstance(cwd, Path) or not cwd.is_dir():
            raise ValueError("sandbox tool cwd must be an existing directory")
        if not tool.executable_matches():
            return RawToolResult(ToolStatus.START_ERROR, None, b"", b"trusted tool executable fingerprint changed")

        adapter = BubblewrapProcessAdapter(
            allowed_executables=(tool.command[0],),
            bubblewrap_path=self._bubblewrap_path,
        )
        execution_id = hashlib.sha256(
            f"{tool.tool_fingerprint}:{cwd.resolve()}".encode("utf-8")
        ).hexdigest()
        limits = ExecutionLimits(
            wall_time_seconds=float(tool.timeout_seconds),
            cpu_time_seconds=min(30.0, float(tool.timeout_seconds)),
            memory_bytes=256 * 1024 * 1024,
            process_count=1,
            output_bytes=tool.max_output_bytes,
            file_size_bytes=max(tool.max_output_bytes, 16 * 1024 * 1024),
            open_file_count=64,
        )
        spec = ExecutionSpec(
            execution_id=execution_id,
            adapter_id=adapter.adapter_id,
            argv=tool.command,
            security=ExecutionSecurityContext(
                organization_id="generated-code-sandbox",
                principal_id="phase4-patch-runtime",
                actor_id="phase4-patch-runtime",
            ),
            limits=limits,
            writable_paths=(str(cwd.resolve()),),
            environment=tuple(tool.environment),
        )
        try:
            result = adapter.execute(spec)
        except ProcessSandboxUnavailable as exc:
            return RawToolResult(ToolStatus.START_ERROR, None, b"", str(exc).encode("utf-8"))

        output = result.output.encode("utf-8", errors="replace")
        if result.outcome.value == "timed_out":
            return RawToolResult(ToolStatus.TIMED_OUT, result.exit_code, output, b"")
        if len(output) > tool.max_output_bytes:
            return RawToolResult(ToolStatus.OUTPUT_LIMIT, result.exit_code, output, b"")
        if result.outcome.value == "succeeded":
            return RawToolResult(ToolStatus.PASSED, result.exit_code, output, b"")
        return RawToolResult(ToolStatus.FAILED, result.exit_code, output, (result.error or "sandbox execution failed").encode("utf-8"))


__all__ = ["BubblewrapToolRunner"]
