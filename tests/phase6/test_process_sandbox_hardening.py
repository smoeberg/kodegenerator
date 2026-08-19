from __future__ import annotations

import pytest

from phase6.execution.process import BubblewrapProcessAdapter
from phase6.execution.sandbox import ExecutionSecurityContext, ExecutionSpec, InvalidExecutionSpec


BWRAP = "/usr/bin/bwrap"
PYTHON = "/usr/bin/python3"


def _spec(path: str) -> ExecutionSpec:
    return ExecutionSpec(
        execution_id="exec-hardening",
        adapter_id="bubblewrap-process",
        argv=(PYTHON, "-c", "print('ok')"),
        security=ExecutionSecurityContext("org-1", "principal-1", "actor-1"),
        writable_paths=(path,),
    )


def test_writable_system_path_is_rejected() -> None:
    adapter = BubblewrapProcessAdapter(allowed_executables=(PYTHON,), bubblewrap_path=BWRAP)
    with pytest.raises(InvalidExecutionSpec, match="under /tmp or /var/tmp"):
        adapter.execute(_spec("/etc"))


def test_writable_root_is_rejected() -> None:
    adapter = BubblewrapProcessAdapter(allowed_executables=(PYTHON,), bubblewrap_path=BWRAP)
    with pytest.raises(InvalidExecutionSpec, match="root cannot be writable"):
        adapter.execute(_spec("/"))
