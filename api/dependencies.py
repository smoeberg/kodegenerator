"""FastAPI dependencies for the canonical DOR runtime."""

import os
from functools import lru_cache

from phase4.implementation_agent import (
    ImplementationAgentRuntime,
    OpenAIImplementationProvider,
)
from runtime.core import DORRuntime


class ImplementationAgentConfigurationError(RuntimeError):
    """The operational implementation-agent provider is not configured."""


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
        )
    except (TypeError, ValueError) as exc:
        raise ImplementationAgentConfigurationError(
            "Implementation Agent configuration is invalid"
        ) from exc
