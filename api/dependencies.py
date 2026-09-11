"""FastAPI dependencies for the canonical DOR runtime."""

import os
from functools import lru_cache
from pathlib import Path

from infrastructure.persistence.bot_catalog_store import BotCatalogStore
from infrastructure.persistence.council_configuration_store import (
    CouncilConfigurationStore,
)
from infrastructure.persistence.evaluation_store import EvaluationStore
from infrastructure.persistence.factory_integration_store import FactoryIntegrationStore
from infrastructure.persistence.factory_store import FactoryStore
from infrastructure.persistence.llm_replay_store import SQLAlchemyLLMReplayStore
from infrastructure.persistence.selection_store import CouncilSelectionStore
from infrastructure.runtime.db import build_session_factory
from phase4.agent_registry import AgentRegistry
from phase4.implementation_agent import (
    GovernedPatchExecutionRuntime,
    ImplementationAgentRuntime,
    OpenAIImplementationProvider,
    PatchWorkspaceError,
    canonical_python_tools,
)
from runtime.core import DORRuntime
from runtime.project_scope_runtime import ActiveProjectScopeResolver
from services.bot_catalog import BotCatalogService
from services.council_selection import CouncilSelectionService
from services.governed_llm import GovernedLLMRuntime
from services.implementation_ai_settings import (
    DEFAULT_OPENAI_BASE_URL,
    effective_implementation_ai_config,
    normalize_openai_base_url,
)
from services.llm_adapters import OpenAIAdapter
from services.runtime_failure_remediation import (
    GovernanceCoordinatorRemediationAdapter,
    RedmineIssueAdapter,
    RepositoryWorkQueueAdapter,
    RuntimeFailureRemediation,
    ShipGateDraftPRAdapter,
    VerifiedAuthorityReleaseAdapter,
)
from services.runtime_settings import (
    SettingsEncryptionUnavailable,
    SettingsSecretUnreadable,
)
from services.ship_gate import ShipGate
from services.side_effects import SideEffectCoordinator
from services.swarm_control_store import SwarmControlStore


class ImplementationAgentConfigurationError(RuntimeError):
    """The operational implementation-agent provider is not configured."""


@lru_cache(maxsize=1)
def get_pipeline_llm_runtime() -> GovernedLLMRuntime:
    """Build the explicit fail-closed structured LLM proposal boundary."""
    api_key = os.getenv("OPENAI_API_KEY")
    model = os.getenv("DOR_PIPELINE_LLM_MODEL")
    if not api_key or not model:
        raise ImplementationAgentConfigurationError(
            "OPENAI_API_KEY and DOR_PIPELINE_LLM_MODEL are required"
        )
    adapter = OpenAIAdapter(
        api_key=api_key,
        model=model,
        max_retries=_positive_int_environment("DOR_PIPELINE_LLM_RETRIES", 2),
        timeout_seconds=_positive_int_environment("DOR_PIPELINE_LLM_TIMEOUT_SECONDS", 60),
        max_output_tokens=_positive_int_environment("DOR_PIPELINE_LLM_MAX_OUTPUT_TOKENS", 2048),
    )
    replay_store = SQLAlchemyLLMReplayStore(
        build_session_factory(os.getenv("DATABASE_URL", "sqlite:///./dor_runtime.db")),
        lease_seconds=_positive_int_environment("DOR_PIPELINE_LLM_LEASE_SECONDS", 180),
    )
    return GovernedLLMRuntime(adapter, replay_store=replay_store)


@lru_cache(maxsize=1)
def get_dor() -> DORRuntime:
    runtime = DORRuntime(os.getenv("DATABASE_URL", "sqlite:///./dor_runtime.db"))
    runtime.boot()
    return runtime


@lru_cache(maxsize=1)
def get_agent_registry() -> AgentRegistry:
    return AgentRegistry()


@lru_cache(maxsize=1)
def get_bot_catalog_service() -> BotCatalogService:
    return BotCatalogService(
        BotCatalogStore(build_session_factory(os.getenv("DATABASE_URL", "sqlite:///./dor_runtime.db"))),
        get_agent_registry(),
    )


@lru_cache(maxsize=1)
def get_council_configuration_store() -> CouncilConfigurationStore:
    return CouncilConfigurationStore(
        build_session_factory(os.getenv("DATABASE_URL", "sqlite:///./dor_runtime.db"))
    )


@lru_cache(maxsize=1)
def get_council_selection_service() -> CouncilSelectionService:
    factory = build_session_factory(os.getenv("DATABASE_URL", "sqlite:///./dor_runtime.db"))
    return CouncilSelectionService(
        BotCatalogStore(factory),
        CouncilConfigurationStore(factory),
        CouncilSelectionStore(factory),
    )


def _session_factory():
    return build_session_factory(os.getenv("DATABASE_URL", "sqlite:///./dor_runtime.db"))


@lru_cache(maxsize=1)
def get_swarm_control_store() -> SwarmControlStore:
    return SwarmControlStore(_session_factory())


@lru_cache(maxsize=1)
def get_evaluation_store() -> EvaluationStore:
    return EvaluationStore(_session_factory())


@lru_cache(maxsize=1)
def get_factory_store() -> FactoryStore:
    return FactoryStore(_session_factory())


@lru_cache(maxsize=1)
def get_factory_integration_store() -> FactoryIntegrationStore:
    return FactoryIntegrationStore(_session_factory())


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
        raise ImplementationAgentConfigurationError(f"{name} must be a positive integer")
    return value


def _active_scope_resolver():
    return ActiveProjectScopeResolver(get_dor().database).require


def _implementation_provider_config() -> tuple[str | None, str | None, str]:
    """Resolve tenant settings only inside a tenant-pinned worker process.

    The direct API dependency remains environment-backed because its requests can
    span organizations. A worker is pinned to exactly one pipeline organization,
    so it may safely resolve that organization's stored AI configuration before
    each new implementation task.
    """
    runtime_role = os.getenv("DOR_RUNTIME_ROLE", "").strip().lower()
    organization_id = os.getenv("DOR_PIPELINE_STATE_ORGANIZATION_ID", "").strip()
    if runtime_role == "worker" and organization_id:
        try:
            config = effective_implementation_ai_config(
                get_dor().database,
                organization_id,
            )
        except (SettingsEncryptionUnavailable, SettingsSecretUnreadable, ValueError) as exc:
            raise ImplementationAgentConfigurationError(
                "Implementation Agent stored configuration is unavailable"
            ) from exc
        return (
            str(config.get("api_key") or "").strip() or None,
            str(config.get("model") or "").strip() or None,
            str(config.get("base_url") or DEFAULT_OPENAI_BASE_URL),
        )

    base_url = normalize_openai_base_url(
        os.getenv("DOR_IMPLEMENTATION_OPENAI_BASE_URL", "").strip()
        or DEFAULT_OPENAI_BASE_URL
    )
    return (
        os.getenv("OPENAI_API_KEY"),
        os.getenv("DOR_IMPLEMENTATION_MODEL"),
        base_url,
    )


def get_implementation_agent_runtime() -> ImplementationAgentRuntime:
    """Build a fresh runtime so newly saved worker settings apply to new tasks."""
    api_key, model, base_url = _implementation_provider_config()
    configured_resources = os.getenv("DOR_IMPLEMENTATION_ALLOWED_RESOURCES")
    if not api_key:
        raise ImplementationAgentConfigurationError("OPENAI_API_KEY or a saved AI API key is required for the Implementation Agent")
    if not model:
        raise ImplementationAgentConfigurationError("DOR_IMPLEMENTATION_MODEL or a saved AI model is required for the Implementation Agent")
    if not configured_resources:
        raise ImplementationAgentConfigurationError("DOR_IMPLEMENTATION_ALLOWED_RESOURCES is required")
    resources = tuple(item.strip() for item in configured_resources.split(","))
    if any(not item for item in resources):
        raise ImplementationAgentConfigurationError("DOR_IMPLEMENTATION_ALLOWED_RESOURCES contains an empty resource")
    try:
        provider = OpenAIImplementationProvider(
            api_key=api_key,
            model=model,
            base_url=base_url,
            max_input_bytes=_positive_int_environment("DOR_IMPLEMENTATION_MAX_INPUT_BYTES", 512 * 1024),
            max_output_bytes=_positive_int_environment("DOR_IMPLEMENTATION_MAX_OUTPUT_BYTES", 512 * 1024),
        )
        return ImplementationAgentRuntime(
            provider=provider,
            allowed_resources=resources,
            max_files=_positive_int_environment("DOR_IMPLEMENTATION_MAX_FILES", 8),
            max_changed_lines=_positive_int_environment("DOR_IMPLEMENTATION_MAX_CHANGED_LINES", 1_000),
            max_context_items=_positive_int_environment("DOR_IMPLEMENTATION_MAX_CONTEXT_ITEMS", 200),
            max_context_bytes=_positive_int_environment("DOR_IMPLEMENTATION_MAX_CONTEXT_BYTES", 512 * 1024),
            active_scope_resolver=_active_scope_resolver(),
        )
    except (TypeError, ValueError) as exc:
        raise ImplementationAgentConfigurationError("Implementation Agent configuration is invalid") from exc


@lru_cache(maxsize=1)
def get_governed_patch_runtime() -> GovernedPatchExecutionRuntime:
    workspace_value = os.getenv("DOR_PATCH_WORKSPACE_ROOT")
    configured_tool_ids = os.getenv("DOR_PATCH_ALLOWED_TOOLS")
    if not workspace_value:
        raise ImplementationAgentConfigurationError("DOR_PATCH_WORKSPACE_ROOT is required for governed patch execution")
    workspace = Path(workspace_value)
    if not workspace.is_absolute():
        raise ImplementationAgentConfigurationError("DOR_PATCH_WORKSPACE_ROOT must be an absolute path")
    if not configured_tool_ids:
        raise ImplementationAgentConfigurationError("DOR_PATCH_ALLOWED_TOOLS is required for governed patch execution")
    requested_ids = tuple(item.strip() for item in configured_tool_ids.split(","))
    if any(not item for item in requested_ids) or len(requested_ids) != len(set(requested_ids)):
        raise ImplementationAgentConfigurationError("DOR_PATCH_ALLOWED_TOOLS must contain unique non-empty tool IDs")

    timeout_seconds = _positive_int_environment("DOR_PATCH_TOOL_TIMEOUT_SECONDS", 300)
    max_output_bytes = _positive_int_environment("DOR_PATCH_MAX_TOOL_OUTPUT_BYTES", 256 * 1024)
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
            "DOR_PATCH_ALLOWED_TOOLS contains an unknown tool ID: " + ", ".join(unknown)
        )
    tools = tuple(available[item] for item in requested_ids)
    try:
        return GovernedPatchExecutionRuntime(
            proposal_runtime=get_implementation_agent_runtime(),
            workspace_root=workspace,
            tools=tools,
            max_file_bytes=_positive_int_environment("DOR_PATCH_MAX_FILE_BYTES", 16 * 1024 * 1024),
            max_workspace_files=_positive_int_environment("DOR_PATCH_MAX_WORKSPACE_FILES", 20_000),
            max_workspace_bytes=_positive_int_environment("DOR_PATCH_MAX_WORKSPACE_BYTES", 256 * 1024 * 1024),
            patch_timeout_seconds=_positive_int_environment("DOR_PATCH_APPLY_TIMEOUT_SECONDS", 30),
            active_scope_resolver=_active_scope_resolver(),
        )
    except (PatchWorkspaceError, TypeError, ValueError) as exc:
        raise ImplementationAgentConfigurationError("Governed patch-execution configuration is invalid") from exc


def build_governance_implementation_runtimes(workspace_root: Path, materialize):
    """Build proposal/apply runtimes sharing one proposal runtime for Governance Coder."""
    proposal_runtime = get_implementation_agent_runtime()
    configured_tool_ids = os.getenv("DOR_PATCH_ALLOWED_TOOLS")
    if not configured_tool_ids:
        raise ImplementationAgentConfigurationError("DOR_PATCH_ALLOWED_TOOLS is required")
    requested_ids = tuple(item.strip() for item in configured_tool_ids.split(","))
    if any(not item for item in requested_ids) or len(requested_ids) != len(set(requested_ids)):
        raise ImplementationAgentConfigurationError(
            "DOR_PATCH_ALLOWED_TOOLS must contain unique non-empty tool IDs"
        )
    available = {tool.tool_id: tool for tool in canonical_python_tools(
        timeout_seconds=_positive_int_environment("DOR_PATCH_TOOL_TIMEOUT_SECONDS", 300),
        max_output_bytes=_positive_int_environment("DOR_PATCH_MAX_TOOL_OUTPUT_BYTES", 256 * 1024),
    )}
    unknown = tuple(item for item in requested_ids if item not in available)
    if unknown:
        raise ImplementationAgentConfigurationError(
            "DOR_PATCH_ALLOWED_TOOLS contains an unknown tool ID: " + ", ".join(unknown)
        )
    try:
        patch_runtime = GovernedPatchExecutionRuntime(
            proposal_runtime=proposal_runtime, workspace_root=workspace_root,
            tools=tuple(available[item] for item in requested_ids), materialize=materialize,
            max_file_bytes=_positive_int_environment("DOR_PATCH_MAX_FILE_BYTES", 16 * 1024 * 1024),
            max_workspace_files=_positive_int_environment("DOR_PATCH_MAX_WORKSPACE_FILES", 20_000),
            max_workspace_bytes=_positive_int_environment("DOR_PATCH_MAX_WORKSPACE_BYTES", 256 * 1024 * 1024),
            patch_timeout_seconds=_positive_int_environment("DOR_PATCH_APPLY_TIMEOUT_SECONDS", 30),
            active_scope_resolver=_active_scope_resolver(),
        )
    except (PatchWorkspaceError, TypeError, ValueError) as exc:
        raise ImplementationAgentConfigurationError(
            "Governance implementation runtime configuration is invalid"
        ) from exc
    return proposal_runtime, patch_runtime


def build_runtime_failure_remediation(
    *, ticker, governance_coordinator, problem_factory, reproduction_runner,
    patch_loader, scope_validator, verification, release_authority, publisher,
    knowledge_record, test_results, audit_harness, metadata_factory,
    required_capability, side_effect_store,
) -> RuntimeFailureRemediation:
    """Bind existing runtimes; dependency wiring grants no authority."""
    effects = SideEffectCoordinator(side_effect_store)
    return RuntimeFailureRemediation(
        issues=RedmineIssueAdapter(ticker),
        work_queue=RepositoryWorkQueueAdapter(
            _session_factory(), scope_validator=scope_validator
        ),
        remediation=GovernanceCoordinatorRemediationAdapter(
            governance_coordinator, problem_factory, reproduction_runner, patch_loader
        ),
        verification=verification,
        release_authority=VerifiedAuthorityReleaseAdapter(release_authority),
        draft_prs=ShipGateDraftPRAdapter(
            ShipGate(publisher), record=knowledge_record, test_results=test_results,
            audit_harness=audit_harness, metadata_factory=metadata_factory,
            side_effects=effects,
        ),
        required_capability=required_capability,
        side_effects=effects,
    )
