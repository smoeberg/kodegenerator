"""Execution module for pipeline task executors.

This package contains task executors used by the software factory pipeline.
"""

from execution.pipeline_executors import (
    ArchitectureExecutor,
    ContractsExecutor,
    CodeExecutor,
    TestsExecutor,
    RunTestsExecutor,
    DeployExecutor,
    ReleaseExecutor,
    build_pipeline_executor_registry,
)

# PR #126 introduces TestGeneratorExecutor as the canonical name; TestsExecutor
# remains an alias for backwards compatibility.
try:
    from execution.pipeline_executors import TestGeneratorExecutor
except ImportError:  # pragma: no cover - older pipeline_executors without alias
    TestGeneratorExecutor = TestsExecutor  # type: ignore[misc,assignment]

__all__ = [
    "ArchitectureExecutor",
    "ContractsExecutor",
    "CodeExecutor",
    "TestsExecutor",
    "TestGeneratorExecutor",
    "RunTestsExecutor",
    "DeployExecutor",
    "ReleaseExecutor",
    "build_pipeline_executor_registry",
]
