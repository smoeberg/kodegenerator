"""Execution package with lazy compatibility exports.

Importing a focused execution submodule must not initialize every deploy,
release, HTTP, and provider adapter. Compatibility names remain available via
PEP 562 and load the canonical pipeline module only when explicitly requested.
"""

from __future__ import annotations

from typing import Any

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


def __getattr__(name: str) -> Any:
    if name not in __all__:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    from execution import pipeline_executors

    return getattr(pipeline_executors, name)
