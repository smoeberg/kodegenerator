"""Deterministic test provider for the implementation-agent contract."""

from __future__ import annotations

from collections.abc import Mapping

from .models import ImplementationRequest, PatchCandidate


class DeterministicFakeImplementationProvider:
    """Return an exact configured diff for an exact request fingerprint."""

    def __init__(
        self, responses: Mapping[str, str], *, provider_id: str = "fake.deterministic"
    ) -> None:
        if not isinstance(provider_id, str) or not provider_id.strip():
            raise ValueError("provider_id must be a non-empty string")
        self._provider_id = provider_id
        self._responses = dict(responses)
        self._calls: list[str] = []

    @property
    def provider_id(self) -> str:
        return self._provider_id

    @property
    def calls(self) -> tuple[str, ...]:
        return tuple(self._calls)

    def propose_patch(self, request: ImplementationRequest) -> PatchCandidate:
        fingerprint = request.request_fingerprint
        self._calls.append(fingerprint)
        try:
            unified_diff = self._responses[fingerprint]
        except KeyError as exc:
            raise LookupError(
                f"no deterministic response configured for request {fingerprint}"
            ) from exc
        return PatchCandidate(unified_diff=unified_diff)
