"""Deterministic provider for Project Audit Agent contract tests."""

from __future__ import annotations

from collections.abc import Mapping

from .models import ProjectAuditCandidate, ProjectAuditRequest


class DeterministicFakeProjectAuditProvider:
    """Return an exact candidate for an exact immutable audit request."""

    def __init__(
        self,
        responses: Mapping[str, ProjectAuditCandidate],
        *,
        provider_id: str = "fake.project-audit.deterministic",
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

    def audit_project(self, request: ProjectAuditRequest) -> ProjectAuditCandidate:
        fingerprint = request.request_fingerprint
        self._calls.append(fingerprint)
        try:
            return self._responses[fingerprint]
        except KeyError as exc:
            raise LookupError(
                f"no deterministic audit configured for request {fingerprint}"
            ) from exc
