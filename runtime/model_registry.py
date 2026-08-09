"""Provider-neutral model declarations for the legacy AI execution boundary.

This module is a metadata catalog, not a provider implementation.  Credentials
belong to provider adapters and are deliberately excluded from the model.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class ModelProvider(str, Enum):
    OPENAI = "OpenAI"
    ANTHROPIC = "Anthropic"
    DEEPSEEK = "DeepSeek"
    GOOGLE = "Google"
    MISTRAL = "Mistral"
    LOCAL = "Local"


@dataclass(frozen=True)
class Model:
    """Immutable, non-secret declaration of an available language model."""

    id: str
    name: str
    provider: ModelProvider
    capabilities: tuple[str, ...] = field(default_factory=tuple)
    cost_per_token: float = 0.0
    latency: float = 0.0
    max_tokens: int = 0
    context_size: int = 0
    quality_score: float = 0.0
    reliability: float = 0.0
    availability: float = 0.0

    def __post_init__(self) -> None:
        if not self.id.strip() or not self.name.strip():
            raise ValueError("Model requires non-empty id and name")
        if not isinstance(self.provider, ModelProvider):
            raise TypeError("provider must be ModelProvider")
        if self.cost_per_token < 0 or self.latency < 0:
            raise ValueError("Model cost and latency must be non-negative")
        if self.max_tokens < 0 or self.context_size < 0:
            raise ValueError("Model token limits must be non-negative")
        for field_name in ("quality_score", "reliability", "availability"):
            value = getattr(self, field_name)
            if not 0.0 <= value <= 1.0:
                raise ValueError(f"{field_name} must be between 0 and 1")
        object.__setattr__(self, "capabilities", tuple(self.capabilities))


class ModelRegistry:
    """In-memory catalog for provider-neutral model declarations."""

    def __init__(self) -> None:
        self.models: dict[str, Model] = {}

    def add_model(self, model: Model) -> None:
        self.models.setdefault(model.id, model)

    def get_model(self, model_id: str) -> Model | None:
        return self.models.get(model_id)

    def get_models_by_capability(self, capability: str) -> list[Model]:
        return [
            model for model in self.models.values() if capability in model.capabilities
        ]

    def get_models_by_provider(self, provider: ModelProvider) -> list[Model]:
        return [model for model in self.models.values() if model.provider is provider]

    def get_best_model(
        self,
        capabilities: list[str],
        constraints: dict[str, float] | None = None,
    ) -> Model | None:
        candidates = [
            model
            for model in self.models.values()
            if all(capability in model.capabilities for capability in capabilities)
        ]
        limits = constraints or {}
        candidates = [
            model
            for model in candidates
            if model.cost_per_token <= limits.get("max_cost", float("inf"))
            and model.latency <= limits.get("max_latency", float("inf"))
            and model.quality_score >= limits.get("min_quality", 0.0)
        ]
        if not candidates:
            return None
        return max(
            candidates,
            key=lambda model: (
                model.quality_score,
                model.reliability,
                model.availability,
                -model.cost_per_token,
                -model.latency,
                model.id,
            ),
        )
