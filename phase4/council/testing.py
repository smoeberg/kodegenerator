"""Deterministic Council provider for contract and integration tests."""

from __future__ import annotations

from collections.abc import Mapping

from .roles import (
    CouncilRole,
    CouncilTurnDecision,
    CouncilTurnKind,
    CouncilTurnRequest,
    CouncilTurnResponse,
)

CouncilScriptKey = tuple[int, CouncilRole, CouncilTurnKind]
CouncilScriptValue = CouncilTurnDecision | Exception


class DeterministicFakeCouncilProvider:
    """Return scripted decisions bound to each exact content-addressed turn."""

    def __init__(
        self,
        responses: Mapping[
            CouncilScriptKey,
            CouncilScriptValue | tuple[CouncilScriptValue, ...],
        ],
        *,
        provider_id: str = "fake.council.deterministic",
    ) -> None:
        if not isinstance(provider_id, str) or not provider_id.strip():
            raise ValueError("provider_id must be a non-empty string")
        self._provider_id = provider_id
        self._responses = {
            key: value if isinstance(value, tuple) else (value,)
            for key, value in responses.items()
        }
        self._calls: list[CouncilTurnRequest] = []
        self._attempts: dict[CouncilScriptKey, int] = {}

    @property
    def provider_id(self) -> str:
        return self._provider_id

    @property
    def calls(self) -> tuple[CouncilTurnRequest, ...]:
        return tuple(self._calls)

    def deliberate(self, request: CouncilTurnRequest) -> CouncilTurnResponse:
        self._calls.append(request)
        key = (request.round_number, request.role, request.turn_kind)
        options = self._responses.get(key)
        if options is None:
            raise LookupError(f"no deterministic Council response configured for {key}")
        attempt = self._attempts.get(key, 0)
        self._attempts[key] = attempt + 1
        selected = options[min(attempt, len(options) - 1)]
        if isinstance(selected, Exception):
            raise selected
        return CouncilTurnResponse(
            turn_id=request.turn_id,
            agent_identity=request.agent_identity,
            role=request.role,
            **selected.model_dump(),
        )
