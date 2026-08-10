from __future__ import annotations

import os

import pytest

from phase6.execution.process import BubblewrapProcessAdapter, ProcessSandboxUnavailable
from phase6.execution.sandbox import (
    ExecutionLimits,
    ExecutionOutcome,
    ExecutionSecurityContext,
    ExecutionSpec,
    InvalidExecutionSpec,
)


def _spec(*, executable: str = "/usr/bin/python3", network: tuple[str, ...] = ()) -> ExecutionSpec:
    return ExecutionSpec(
        execution_id="exec-1",
        adapter_id="bubblewrap-process",
        argv=(executable, "-c", "print('ok')"),
        security=ExecutionSecurityContext(
            organization_id="org-1",
            principal_id="principal-1",
            actor_id="actor-1",
        ),
        limits=ExecutionLimits(wall_time_seconds=5, cpu_time_seconds=2, memory_bytes=64 * 1024 * 1024),
        network_allowlist=network,
    )


def test_adapter_fails_closed_without_bubblewrap() -> None:
    with pytest.raises(ProcessSandboxUnavailable):
        BubblewrapProcessAdapter(allowed_executables=("/usr/bin/python3",), bubblewrap_path=None)


def test_adapter_rejects_non_allowlisted_executable() -> None:
    adapter = BubblewrapProcessAdapter(
        allowed_executables=("/usr/bin/python3",),
        bubblewrap_path="/usr/bin/bwrap",
    )

    with pytest.raises(InvalidExecutionSpec, match="not allowlisted"):
        adapter.execute(_spec(executable="/bin/sh"))


def test_adapter_rejects_network_allowlist_until_backend_supports_it() -> None:
    adapter = BubblewrapProcessAdapter(
        allowed_executables=("/usr/bin/python3",),
        bubblewrap_path="/usr/bin/bwrap",
    )

    with pytest.raises(InvalidExecutionSpec, match="network allowlists"):
        adapter.execute(_spec(network=("example.com",)))


def test_bubblewrap_command_unshares_network_and_pid() -> None:
    adapter = BubblewrapProcessAdapter(
        allowed_executables=("/usr/bin/python3",),
        bubblewrap_path="/usr/bin/bwrap",
    )

    command = adapter._build_command(_spec())

    assert "--unshare-net" in command
    assert "--unshare-pid" in command
    assert "--ro-bind" in command
    assert command[-3:] == ["/", "--", "/usr/bin/python3"] or command[-2:] != ["--", "/bin/sh"]


def test_writable_path_must_exist(tmp_path) -> None:
    adapter = BubblewrapProcessAdapter(
        allowed_executables=("/usr/bin/python3",),
        bubblewrap_path="/usr/bin/bwrap",
    )
    missing = os.path.join(str(tmp_path), "missing")
    spec = ExecutionSpec(
        execution_id="exec-1",
        adapter_id="bubblewrap-process",
        argv=("/usr/bin/python3", "-c", "print('ok')"),
        security=ExecutionSecurityContext("org-1", "principal-1", "actor-1"),
        writable_paths=(missing,),
    )

    with pytest.raises(InvalidExecutionSpec, match="does not exist"):
        adapter.execute(spec)
