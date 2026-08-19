from __future__ import annotations

import os

import pytest

from phase6.execution.process import BubblewrapProcessAdapter, ProcessSandboxUnavailable
from phase6.execution.sandbox import (
    ExecutionLimits,
    ExecutionSecurityContext,
    ExecutionSpec,
    InvalidExecutionSpec,
)


import shutil

pytestmark = pytest.mark.skipif(
    not shutil.which("bwrap") or not os.access(shutil.which("bwrap"), os.X_OK),
    reason="Bubblewrap (bwrap) is not available on this system"
)

BWRAP = shutil.which("bwrap") or "/usr/bin/bwrap"
PYTHON = "/usr/bin/python3"


def _spec(*, executable: str = PYTHON, network: tuple[str, ...] = ()) -> ExecutionSpec:
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


def test_adapter_fails_closed_for_missing_bubblewrap() -> None:
    with pytest.raises(ProcessSandboxUnavailable):
        BubblewrapProcessAdapter(
            allowed_executables=(PYTHON,),
            bubblewrap_path="/definitely/missing/bwrap",
        )


def test_adapter_rejects_non_allowlisted_executable() -> None:
    adapter = BubblewrapProcessAdapter(
        allowed_executables=(PYTHON,),
        bubblewrap_path=BWRAP,
    )

    with pytest.raises(InvalidExecutionSpec, match="not allowlisted"):
        adapter.execute(_spec(executable="/bin/sh"))


def test_adapter_rejects_network_allowlist_until_backend_supports_it() -> None:
    adapter = BubblewrapProcessAdapter(
        allowed_executables=(PYTHON,),
        bubblewrap_path=BWRAP,
    )

    with pytest.raises(InvalidExecutionSpec, match="network allowlists"):
        adapter.execute(_spec(network=("example.com",)))


def test_bubblewrap_command_unshares_network_and_pid() -> None:
    adapter = BubblewrapProcessAdapter(
        allowed_executables=(PYTHON,),
        bubblewrap_path=BWRAP,
    )

    command = adapter._build_command(_spec())

    assert "--unshare-net" in command
    assert "--unshare-pid" in command
    assert "--ro-bind" in command
    assert command[command.index("--") + 1] == PYTHON


def test_writable_path_must_exist(tmp_path) -> None:
    adapter = BubblewrapProcessAdapter(
        allowed_executables=(PYTHON,),
        bubblewrap_path=BWRAP,
    )
    missing = os.path.join(str(tmp_path), "missing")
    spec = ExecutionSpec(
        execution_id="exec-1",
        adapter_id="bubblewrap-process",
        argv=(PYTHON, "-c", "print('ok')"),
        security=ExecutionSecurityContext("org-1", "principal-1", "actor-1"),
        writable_paths=(missing,),
    )

    with pytest.raises(InvalidExecutionSpec, match="does not exist"):
        adapter.execute(spec)


def test_writable_host_path_outside_temp_is_rejected() -> None:
    adapter = BubblewrapProcessAdapter(
        allowed_executables=(PYTHON,),
        bubblewrap_path=BWRAP,
    )
    spec = ExecutionSpec(
        execution_id="exec-1",
        adapter_id="bubblewrap-process",
        argv=(PYTHON, "-c", "print('ok')"),
        security=ExecutionSecurityContext("org-1", "principal-1", "actor-1"),
        writable_paths=("/etc",),
    )
    with pytest.raises(InvalidExecutionSpec, match="under /tmp or /var/tmp"):
        adapter.execute(spec)


def test_writable_symlink_is_rejected(tmp_path) -> None:
    adapter = BubblewrapProcessAdapter(
        allowed_executables=(PYTHON,),
        bubblewrap_path=BWRAP,
    )
    real = tmp_path / "real"
    real.mkdir()
    link = tmp_path / "link"
    link.symlink_to(real, target_is_directory=True)
    spec = ExecutionSpec(
        execution_id="exec-1",
        adapter_id="bubblewrap-process",
        argv=(PYTHON, "-c", "print('ok')"),
        security=ExecutionSecurityContext("org-1", "principal-1", "actor-1"),
        writable_paths=(str(link),),
    )
    with pytest.raises(InvalidExecutionSpec, match="must not be symlinks"):
        adapter.execute(spec)
