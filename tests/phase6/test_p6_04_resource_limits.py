from __future__ import annotations

import resource

import pytest

from phase6.execution.process import _ProcessLimits, _apply_limits
from phase6.execution.sandbox import ExecutionLimits


def test_execution_limits_reject_output_larger_than_file_limit() -> None:
    with pytest.raises(ValueError, match="output_bytes"):
        ExecutionLimits(output_bytes=2_000, file_size_bytes=1_000)


def test_execution_limits_expose_explicit_resource_bounds() -> None:
    limits = ExecutionLimits(
        wall_time_seconds=20,
        cpu_time_seconds=10,
        memory_bytes=128 * 1024 * 1024,
        process_count=3,
        output_bytes=8_000,
        file_size_bytes=16_000,
        open_file_count=32,
    )

    assert limits.process_count == 3
    assert limits.output_bytes == 8_000
    assert limits.file_size_bytes == 16_000
    assert limits.open_file_count == 32


def test_apply_limits_sets_all_hard_resource_bounds(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[int, tuple[int, int]]] = []

    def fake_setrlimit(kind: int, values: tuple[int, int]) -> None:
        calls.append((kind, values))

    monkeypatch.setattr(resource, "setrlimit", fake_setrlimit)

    _apply_limits(
        _ProcessLimits(
            cpu_seconds=7,
            memory_bytes=64 * 1024 * 1024,
            process_count=2,
            file_size_bytes=4_096,
            open_file_count=24,
        )
    )

    assert dict(calls) == {
        resource.RLIMIT_CPU: (7, 7),
        resource.RLIMIT_AS: (64 * 1024 * 1024, 64 * 1024 * 1024),
        resource.RLIMIT_NPROC: (2, 2),
        resource.RLIMIT_FSIZE: (4_096, 4_096),
        resource.RLIMIT_NOFILE: (24, 24),
        resource.RLIMIT_CORE: (0, 0),
    }


def test_process_limit_is_not_rounded_up() -> None:
    limits = ExecutionLimits(process_count=1)
    assert limits.process_count == 1
    assert _ProcessLimits(
        cpu_seconds=1,
        memory_bytes=1,
        process_count=limits.process_count,
        file_size_bytes=1,
        open_file_count=1,
    ).process_count == 1
