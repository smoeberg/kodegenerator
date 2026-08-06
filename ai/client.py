"""Provider-neutral AI boundary reserved for the Phase 3+ agent runtime.

The foundation deliberately does not pretend to provide an LLM integration. This
module is import-safe and exposes the contract that a future provider adapter can
implement without coupling the persistence/runtime foundation to an SDK.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional, Protocol


class ModelLike(Protocol):
    id: str
    provider: Any


@dataclass(frozen=True)
class AIClient:
    """Explicitly non-operational AI boundary for pre-Phase-3 code."""

    async def generate_response(
        self,
        model: ModelLike,
        prompt: str,
        system_message: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
    ) -> str:
        raise NotImplementedError(
            "LLM provider integration belongs to the Phase 3+ AI runtime contract"
        )
