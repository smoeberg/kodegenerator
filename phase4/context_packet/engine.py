"""Reference implementation of the AI-2 Context Packet Engine."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Iterable, Optional

from .models import ContextItem, ContextPacket, ContextRequest


class ContextError(Exception):
    """Base error for context assembly failures."""


class ContextLimitError(ContextError):
    """Context cannot be represented within the requested bounds."""


class ContextSourceError(ContextError):
    """A context source supplied invalid data."""


class ContextPacketEngine:
    """Assemble deterministic context without granting authority.

    AI-2 owns selection, normalization, ordering, provenance and size bounds.
    It deliberately does not inspect or decide permissions; callers must supply
    the context items that are already eligible for the request.
    """

    def __init__(self) -> None:
        self._audit: list[dict[str, object]] = []

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()

    @staticmethod
    def _estimate_bytes(items: tuple[ContextItem, ...]) -> int:
        return sum(len(str(item.canonical()).encode("utf-8")) for item in items)

    def build(
        self,
        request: ContextRequest,
        items: Iterable[ContextItem],
        *,
        actor: str = "context-engine",
    ) -> ContextPacket:
        if not isinstance(request, ContextRequest):
            raise ContextError("request must be ContextRequest")
        if not actor or not isinstance(actor, str):
            raise ContextError("actor must be a non-empty string")

        normalized = list(items)
        if any(not isinstance(item, ContextItem) for item in normalized):
            raise ContextSourceError("all context items must be ContextItem values")

        requested = set(request.requested_keys)
        if requested:
            normalized = [item for item in normalized if item.key in requested]

        allowed = set(request.allowed_sensitivity)
        normalized = [item for item in normalized if item.sensitivity in allowed]

        # Stable ordering is part of the AI-2 contract. Relevance is primary;
        # source/key are deterministic tie-breakers. No model-generated ranking.
        normalized.sort(key=lambda item: (-item.relevance, item.source, item.key))

        selected: list[ContextItem] = []
        truncated = False
        for item in normalized:
            if len(selected) >= request.max_items:
                truncated = True
                break
            candidate = tuple(selected + [item])
            if self._estimate_bytes(candidate) > request.max_bytes:
                truncated = True
                continue
            selected.append(item)

        packet_items = tuple(selected)
        packet_id = ContextPacket.derive_id(request.agent_identity, request.purpose, packet_items)
        packet = ContextPacket(
            packet_id=packet_id,
            agent_identity=request.agent_identity,
            purpose=request.purpose,
            items=packet_items,
            created_at=self._now(),
            truncated=truncated,
        )
        self._audit.append(
            {
                "operation": "build",
                "packet_id": packet.packet_id,
                "agent_identity": request.agent_identity,
                "actor": actor,
                "timestamp": packet.created_at,
                "item_count": len(packet.items),
                "truncated": packet.truncated,
            }
        )
        return packet

    def audit_trail(self, packet_id: Optional[str] = None) -> list[dict[str, object]]:
        if packet_id is None:
            return [dict(entry) for entry in self._audit]
        return [dict(entry) for entry in self._audit if entry["packet_id"] == packet_id]
