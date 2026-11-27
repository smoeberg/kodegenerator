"""Resolve a Bot Catalog profile into a governed, runnable model.

Provider, endpoint and model come from the Bot Catalog; the API key is
resolved internally through ``BotProviderCredentialStore`` (AGENTS.md,
provider-neutral resolution). The chain is profile -> deployment ->
connection, and every link must be enabled and at the version the link
above it pins. Anything else fails closed. The credential never leaves this
module except inside the adapter that uses it.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from domain.agent_job import AgentIdentity
from services.governed_llm import GovernedLLMRuntime, LLMReplayStore
from services.llm_adapters import (
    AnthropicAdapter,
    DeepSeekAdapter,
    MistralAdapter,
    OpenAIAdapter,
    RoolAIAdapter,
)

#: Adapter types that can be built from a catalog connection and a key.
SUPPORTED_ADAPTERS: dict[str, type] = {
    "openai": OpenAIAdapter,
    "anthropic": AnthropicAdapter,
    "mistral": MistralAdapter,
    "deepseek": DeepSeekAdapter,
    "rool": RoolAIAdapter,
}


class BotModelResolutionError(RuntimeError):
    """A bot profile cannot be turned into a trustworthy runnable model."""


class CatalogReader(Protocol):
    def get_profile(
        self, organization_id: str, bot_profile_id: str, version: int | None = None
    ) -> Any: ...

    def get_deployment(
        self, organization_id: str, deployment_id: str, revision: int | None = None
    ) -> Any: ...

    def get_connection(
        self, organization_id: str, connection_id: str, version: int | None = None
    ) -> Any: ...


class CredentialReader(Protocol):
    def secret(self, organization_id: str, connection_id: str) -> str | None: ...


@dataclass(frozen=True)
class BoundModel:
    """A runnable model and the non-secret identity of who it is."""

    runtime: GovernedLLMRuntime
    identity: AgentIdentity
    prompt_version: str
    max_input_tokens: int
    max_output_tokens: int

    @property
    def model(self) -> str:
        return str(self.identity.model)


def bound_model(
    provider: Any,
    *,
    brand: str,
    bot_profile_id: str,
    prompt_version: str = "v1",
    max_input_tokens: int = 32_000,
    max_output_tokens: int = 4_096,
    replay_store: LLMReplayStore | None = None,
) -> BoundModel:
    """Bind any structured provider (real adapter or test double)."""
    if not str(brand or "").strip():
        raise BotModelResolutionError("a bound model needs a producer (brand)")
    return BoundModel(
        runtime=GovernedLLMRuntime(provider, replay_store=replay_store),
        identity=AgentIdentity(
            tool=f"llm:{provider.provider}",
            bot_profile_id=bot_profile_id,
            provider=provider.provider,
            model=provider.model,
            brand=brand.strip().lower(),
        ),
        prompt_version=prompt_version,
        max_input_tokens=max_input_tokens,
        max_output_tokens=max_output_tokens,
    )


def _required(value: Any, kind: str, ref: str) -> Any:
    if value is None:
        raise BotModelResolutionError(f"{kind} {ref} not found")
    return value


def resolve_bot_model(
    catalog: CatalogReader,
    credentials: CredentialReader,
    organization_id: str,
    bot_profile_id: str,
    *,
    replay_store: LLMReplayStore | None = None,
) -> BoundModel:
    try:
        profile = _required(
            catalog.get_profile(organization_id, bot_profile_id),
            "bot profile",
            bot_profile_id,
        )
        deployment = _required(
            catalog.get_deployment(
                organization_id, profile.deployment_id, profile.deployment_revision
            ),
            "deployment",
            f"{profile.deployment_id}@{profile.deployment_revision}",
        )
        connection = _required(
            catalog.get_connection(
                organization_id, deployment.connection_id, deployment.connection_version
            ),
            "connection",
            f"{deployment.connection_id}@{deployment.connection_version}",
        )
    except KeyError as exc:
        raise BotModelResolutionError(
            f"bot profile {bot_profile_id} cannot be resolved: {exc}"
        ) from exc

    if not profile.enabled:
        raise BotModelResolutionError(f"bot profile {bot_profile_id} is disabled")
    if deployment.status != "active":
        raise BotModelResolutionError(
            f"deployment {deployment.deployment_id} is {deployment.status}"
        )
    if not deployment.structured_output:
        raise BotModelResolutionError(
            f"deployment {deployment.deployment_id} has no structured output"
        )
    if not connection.enabled:
        raise BotModelResolutionError(
            f"connection {connection.connection_id} is disabled"
        )
    adapter_class = SUPPORTED_ADAPTERS.get(str(connection.adapter_type).lower())
    if adapter_class is None:
        raise BotModelResolutionError(
            f"unsupported adapter type {connection.adapter_type!r}"
        )
    api_key = credentials.secret(organization_id, connection.connection_id)
    if not api_key:
        raise BotModelResolutionError(
            f"connection {connection.connection_id} has no credential"
        )

    max_output = min(
        int(deployment.max_output_tokens), int(profile.budget_policy.max_output_tokens)
    )
    adapter = adapter_class(
        api_key=api_key,
        model=deployment.model_id,
        base_url=connection.endpoint,
        max_output_tokens=max_output,
    )
    bound = bound_model(
        adapter,
        brand=connection.brand,
        bot_profile_id=bot_profile_id,
        prompt_version=profile.prompt_version,
        max_input_tokens=min(
            int(deployment.max_context_tokens),
            int(profile.budget_policy.max_input_tokens),
        ),
        max_output_tokens=max_output,
        replay_store=replay_store,
    )
    return BoundModel(
        runtime=bound.runtime,
        identity=AgentIdentity(
            tool=bound.identity.tool,
            bot_profile_id=bot_profile_id,
            provider=bound.identity.provider,
            model=deployment.model_id,
            model_version=str(deployment.revision),
            brand=bound.identity.brand,
        ),
        prompt_version=bound.prompt_version,
        max_input_tokens=bound.max_input_tokens,
        max_output_tokens=bound.max_output_tokens,
    )
