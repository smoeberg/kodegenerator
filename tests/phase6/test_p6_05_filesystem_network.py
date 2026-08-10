"""P6-05 security contract tests for filesystem and network restrictions."""

from pathlib import Path

import pytest

from phase6.execution.process import BubblewrapProcessAdapter
from phase6.execution.sandbox import ExecutionLimits, ExecutionSpec, InvalidExecutionSpec


def _spec(executable: str, **kwargs) -> ExecutionSpec:
    return ExecutionSpec(
        execution_id="p6-05-test",
        argv=(executable,),
        limits=ExecutionLimits(
            wall_time_seconds=5,
            cpu_time_seconds=2,
            memory_bytes=128 * 1024 * 1024,
            process_count=8,
            output_bytes=4096,
        ),
        **kwargs,
    )


def test_network_allowlist_is_rejected_by_current_backend(tmp_path: Path):
    adapter = BubblewrapProcessAdapter(allowed_executables=["/usr/bin/true"])
    with pytest.raises(InvalidExecutionSpec, match="network allowlists"):
        adapter.execute(_spec("/usr/bin/true", network_allowlist=("example.com",)))


def test_relative_filesystem_paths_are_rejected():
    adapter = BubblewrapProcessAdapter(allowed_executables=["/usr/bin/true"])
    with pytest.raises(InvalidExecutionSpec, match="absolute"):
        adapter.execute(_spec("/usr/bin/true", read_only_paths=("relative/path",)))


def test_missing_writable_path_is_rejected():
    adapter = BubblewrapProcessAdapter(allowed_executables=["/usr/bin/true"])
    with pytest.raises(InvalidExecutionSpec, match="does not exist"):
        adapter.execute(_spec("/usr/bin/true", writable_paths=("/definitely/missing/p6-05",)))


def test_overlapping_read_only_and_writable_paths_are_rejected(tmp_path: Path):
    adapter = BubblewrapProcessAdapter(allowed_executables=["/usr/bin/true"])
    with pytest.raises(InvalidExecutionSpec):
        adapter.execute(
            _spec(
                "/usr/bin/true",
                read_only_paths=(str(tmp_path),),
                writable_paths=(str(tmp_path),),
            )
        )
