"""Capability and fallback based routing for LLM adapters."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from .llm_adapters import BaseLLMAdapter, LLMResponse, MockLLMAdapter


@dataclass(frozen=True)
class RouteResult:
    """Provider selection metadata."""
    provider: str
    adapter: BaseLLMAdapter


class LLMRouter:
    """Routes requests to named adapters and falls back safely to mock."""

    def __init__(self, adapters: dict[str, BaseLLMAdapter], fallback: Optional[BaseLLMAdapter] = None) -> None:
        self.adapters = dict(adapters)
        self.fallback = fallback or MockLLMAdapter()

    def route(self, provider: str) -> BaseLLMAdapter:
        """Return the configured provider or the fallback adapter."""
        return self.adapters.get(provider.lower(), self.fallback)

    def generate(self, provider: str, prompt: str, schema: Optional[dict[str, object]] = None, temperature: float = 0.2) -> LLMResponse:
        """Generate through a selected provider with adapter-level retries."""
        return self.route(provider).generate(prompt, schema, temperature)
