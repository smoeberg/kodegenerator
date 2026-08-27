from __future__ import annotations

import os
import shutil

import pytest

from phase6.execution.process import BubblewrapProcessAdapter, ProcessSandboxUnavailable
from phase6.execution.sandbox import (
    ExecutionLimits,
    ExecutionSecurityContext,
    ExecutionSpec,
    InvalidExecutionSpec,
)

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
    # bwrap availability is resolved lazily at execute() so that construction
    # and spec validation remain testable without the primitive installed.
    adapter = BubblewrapProcessAdapter(
        allowed_executables=(PYTHON,),
        bubblewrap_path="/definitely/missing/bwrap",
    )
    with pytest.raises(ProcessSandboxUnavailable):
        adapter.execute(_spec())


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
    assert ("--ro-bind", "/", "/") not in tuple(zip(command, command[1:], command[2:]))
    assert command[command.index("--tmpfs") + 1] == "/"
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


def test_explicit_runtime_root_is_mounted_without_exposing_parent(tmp_path) -> None:
    runtime_root = tmp_path / "python-runtime"
    executable = runtime_root / "bin" / "python"
    executable.parent.mkdir(parents=True)
    executable.write_bytes(b"runtime")
    executable.chmod(0o755)
    adapter = BubblewrapProcessAdapter(
        allowed_executables=(str(executable),),
        runtime_roots=(str(runtime_root),),
        bubblewrap_path=BWRAP,
    )
    spec = _spec(executable=str(executable))

    command = adapter._build_command(spec)
    triples = tuple(zip(command, command[1:], command[2:]))

    assert ("--ro-bind", str(runtime_root), str(runtime_root)) in triples
    assert ("--ro-bind", str(tmp_path), str(tmp_path)) not in triples
    assert ("--ro-bind", "/opt", "/opt") not in triples


def test_runtime_root_must_contain_allowlisted_executable(tmp_path) -> None:
    runtime_root = tmp_path / "runtime"
    runtime_root.mkdir()
    with pytest.raises(ValueError, match="contain an allowlisted executable"):
        BubblewrapProcessAdapter(
            allowed_executables=(PYTHON,),
            runtime_roots=(str(runtime_root),),
            bubblewrap_path=BWRAP,
        )
