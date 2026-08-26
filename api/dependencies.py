"""FastAPI dependencies for the canonical DOR runtime."""

import os
from functools import lru_cache
from pathlib import Path

from phase4.execution import SqlAlchemyReplayLedger
from phase4.implementation_agent import (
    GovernedPatchExecutionRuntime,
    ImplementationAgentRuntime,
    OpenAIImplementationProvider,
    PatchWorkspaceError,
    canonical_python_tools,
)
from runtime.core import DORRuntime


class ImplementationAgentConfigurationError(RuntimeError):
    """The operational implementation-agent provider is not configured."""


def _durable_ledger() -> SqlAlchemyReplayLedger:
    """Build the DB-backed replay ledger from the shared runtime database.

    Wires Phase-4 execution to a durable ledger so replay safety (fencing
    tokens, lease expiry) survives process restarts instead of being limited
    to the in-memory ledger.
    """
    return SqlAlchemyReplayLedger(get_dor().database.session_factory)


@lru_cache(maxsize=1)
def get_dor() -> DORRuntime:
    """Return the process-level DOR runtime after applying Alembic migrations."""
    runtime = DORRuntime(os.getenv("DATABASE_URL", "sqlite:///./dor_runtime.db"))
    runtime.boot()
    return runtime


def _positive_int_environment(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        value = int(raw)
    except ValueError as exc:
        raise ImplementationAgentConfigurationError(
            f"{name} must be a positive integer"
        ) from exc
    if value < 1:
        raise ImplementationAgentConfigurationError(
            f"{name} must be a positive integer"
        )
    return value


@lru_cache(maxsize=1)
def get_implementation_agent_runtime() -> ImplementationAgentRuntime:
    """Build the fail-closed, process-level Implementation Agent runtime."""
    api_key = os.getenv("OPENAI_API_KEY")
    model = os.getenv("DOR_IMPLEMENTATION_MODEL")
    configured_resources = os.getenv("DOR_IMPLEMENTATION_ALLOWED_RESOURCES")
    if not api_key:
        raise ImplementationAgentConfigurationError(
            "OPENAI_API_KEY is required for the Implementation Agent"
        )
    if not model:
        raise ImplementationAgentConfigurationError(
            "DOR_IMPLEMENTATION_MODEL is required for the Implementation Agent"
        )
    if not configured_resources:
        raise ImplementationAgentConfigurationError(
            "DOR_IMPLEMENTATION_ALLOWED_RESOURCES is required"
        )
    resources = tuple(item.strip() for item in configured_resources.split(","))
    if any(not item for item in resources):
        raise ImplementationAgentConfigurationError(
            "DOR_IMPLEMENTATION_ALLOWED_RESOURCES contains an empty resource"
        )
    try:
        provider = OpenAIImplementationProvider(
            api_key=api_key,
            model=model,
            max_input_bytes=_positive_int_environment(
                "DOR_IMPLEMENTATION_MAX_INPUT_BYTES", 512 * 1024
            ),
            max_output_bytes=_positive_int_environment(
                "DOR_IMPLEMENTATION_MAX_OUTPUT_BYTES", 512 * 1024
            ),
        )
        return ImplementationAgentRuntime(
            provider=provider,
            allowed_resources=resources,
            max_files=_positive_int_environment("DOR_IMPLEMENTATION_MAX_FILES", 8),
            max_changed_lines=_positive_int_environment(
                "DOR_IMPLEMENTATION_MAX_CHANGED_LINES", 1_000
            ),
            max_context_items=_positive_int_environment(
                "DOR_IMPLEMENTATION_MAX_CONTEXT_ITEMS", 200
            ),
            max_context_bytes=_positive_int_environment(
                "DOR_IMPLEMENTATION_MAX_CONTEXT_BYTES", 512 * 1024
            ),
            ledger=_durable_ledger(),
        )
    except (TypeError, ValueError) as exc:
        raise ImplementationAgentConfigurationError(
            "Implementation Agent configuration is invalid"
        ) from exc


@lru_cache(maxsize=1)
def get_governed_patch_runtime() -> GovernedPatchExecutionRuntime:
    """Build the fail-closed patch/apply runtime with fixed trusted tools."""
    workspace_value = os.getenv("DOR_PATCH_WORKSPACE_ROOT")
    configured_tool_ids = os.getenv("DOR_PATCH_ALLOWED_TOOLS")
    if not workspace_value:
        raise ImplementationAgentConfigurationError(
            "DOR_PATCH_WORKSPACE_ROOT is required for governed patch execution"
        )
    workspace = Path(workspace_value)
    if not workspace.is_absolute():
        raise ImplementationAgentConfigurationError(
            "DOR_PATCH_WORKSPACE_ROOT must be an absolute path"
        )
    if not configured_tool_ids:
        raise ImplementationAgentConfigurationError(
            "DOR_PATCH_ALLOWED_TOOLS is required for governed patch execution"
        )
    requested_ids = tuple(item.strip() for item in configured_tool_ids.split(","))
    if any(not item for item in requested_ids) or len(requested_ids) != len(
        set(requested_ids)
    ):
        raise ImplementationAgentConfigurationError(
            "DOR_PATCH_ALLOWED_TOOLS must contain unique non-empty tool IDs"
        )

    timeout_seconds = _positive_int_environment("DOR_PATCH_TOOL_TIMEOUT_SECONDS", 300)
    max_output_bytes = _positive_int_environment(
        "DOR_PATCH_MAX_TOOL_OUTPUT_BYTES", 256 * 1024
    )
    available = {
        tool.tool_id: tool
        for tool in canonical_python_tools(
            timeout_seconds=timeout_seconds,
            max_output_bytes=max_output_bytes,
        )
    }
    unknown = tuple(item for item in requested_ids if item not in available)
    if unknown:
        raise ImplementationAgentConfigurationError(
            "DOR_PATCH_ALLOWED_TOOLS contains an unknown tool ID: "
            + ", ".join(unknown)
        )
    tools = tuple(available[item] for item in requested_ids)
    try:
        return GovernedPatchExecutionRuntime(
            proposal_runtime=get_implementation_agent_runtime(),
            workspace_root=workspace,
            tools=tools,
            max_file_bytes=_positive_int_environment(
                "DOR_PATCH_MAX_FILE_BYTES", 16 * 1024 * 1024
            ),
            max_workspace_files=_positive_int_environment(
                "DOR_PATCH_MAX_WORKSPACE_FILES", 20_000
            ),
            max_workspace_bytes=_positive_int_environment(
                "DOR_PATCH_MAX_WORKSPACE_BYTES", 256 * 1024 * 1024
            ),
            patch_timeout_seconds=_positive_int_environment(
                "DOR_PATCH_APPLY_TIMEOUT_SECONDS", 30
            ),
            ledger=_durable_ledger(),
        )
    except (PatchWorkspaceError, TypeError, ValueError) as exc:
        raise ImplementationAgentConfigurationError(
            "Governed patch-execution configuration is invalid"
        ) from exc
