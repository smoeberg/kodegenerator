"""Provider-neutral AI-4 adapter for bounded patch proposals."""

from __future__ import annotations

from collections.abc import Iterable
from threading import RLock
from typing import Protocol

from phase4.execution.adapters import AdapterResult
from phase4.execution.models import ExecutionRequest

from .models import (
    IMPLEMENTATION_ACTION,
    ImplementationRequest,
    PatchCandidate,
    PatchProposal,
)


class ImplementationAdapterError(Exception):
    """Base error raised by the implementation adapter boundary."""


class DuplicateImplementationRequestError(ImplementationAdapterError):
    """The application attempted to register the same immutable request twice."""


class ImplementationRequestNotFoundError(ImplementationAdapterError):
    """An execution request referenced no registered implementation request."""


class ImplementationRequestBindingError(ImplementationAdapterError):
    """AI-4 input does not match the registered bounded request."""


class PatchProposalNotFoundError(ImplementationAdapterError):
    """No validated patch proposal has the requested content identity."""


class ImplementationProvider(Protocol):
    """Opaque provider boundary; concrete LLM SDKs live outside this contract."""

    @property
    def provider_id(self) -> str: ...

    def propose_patch(self, request: ImplementationRequest) -> PatchCandidate: ...


class ImplementationExecutionAdapter:
    """Trusted AI-4 adapter that produces, validates, and stores proposals.

    Registration is application-owned. An agent cannot add or widen a request
    through the execution payload.
    """

    def __init__(
        self,
        *,
        adapter_id: str,
        provider: ImplementationProvider,
        requests: Iterable[ImplementationRequest] = (),
    ) -> None:
        if not isinstance(adapter_id, str) or not adapter_id.strip():
            raise ValueError("adapter_id must be a non-empty string")
        provider_id = getattr(provider, "provider_id", None)
        if not isinstance(provider_id, str) or not provider_id.strip():
            raise ValueError("provider must declare a non-empty provider_id")
        if not callable(getattr(provider, "propose_patch", None)):
            raise TypeError("provider must implement propose_patch")

        self._adapter_id = adapter_id
        self._provider = provider
        self._provider_id = provider_id
        self._requests: dict[str, ImplementationRequest] = {}
        self._proposals: dict[str, PatchProposal] = {}
        self._proposal_by_request: dict[str, str] = {}
        self._lock = RLock()
        for request in requests:
            self.register_request(request)

    @property
    def adapter_id(self) -> str:
        return self._adapter_id

    @property
    def action(self) -> str:
        return IMPLEMENTATION_ACTION

    def register_request(self, request: ImplementationRequest) -> None:
        """Register one immutable, pre-bounded request before AI-4 execution."""
        if not isinstance(request, ImplementationRequest):
            raise TypeError("request must be an ImplementationRequest")
        fingerprint = request.request_fingerprint
        with self._lock:
            if fingerprint in self._requests:
                raise DuplicateImplementationRequestError(fingerprint)
            self._requests[fingerprint] = request

    def execute(self, request: ExecutionRequest) -> AdapterResult:
        if not isinstance(request, ExecutionRequest):
            raise TypeError("request must be an ExecutionRequest")
        parameters = dict(request.parameters)
        fingerprint = parameters.get("implementation_request_fingerprint")
        if fingerprint is None:
            raise ImplementationRequestBindingError(
                "execution request is missing the implementation request fingerprint"
            )

        with self._lock:
            implementation_request = self._requests.get(fingerprint)
            if implementation_request is None:
                raise ImplementationRequestNotFoundError(fingerprint)
            self._validate_binding(request, implementation_request)

            existing_id = self._proposal_by_request.get(fingerprint)
            if existing_id is not None:
                return self._result_for(self._proposals[existing_id])

            candidate = self._provider.propose_patch(implementation_request)
            if not isinstance(candidate, PatchCandidate):
                raise TypeError("provider must return PatchCandidate")
            proposal = PatchProposal(
                request=implementation_request,
                provider_id=self._provider_id,
                unified_diff=candidate.unified_diff,
            )
            self._proposals[proposal.proposal_id] = proposal
            self._proposal_by_request[fingerprint] = proposal.proposal_id
            return self._result_for(proposal)

    def get_proposal(self, proposal_id: str) -> PatchProposal:
        with self._lock:
            try:
                return self._proposals[proposal_id]
            except KeyError as exc:
                raise PatchProposalNotFoundError(proposal_id) from exc

    def proposals(self) -> tuple[PatchProposal, ...]:
        with self._lock:
            return tuple(self._proposals[key] for key in sorted(self._proposals))

    @staticmethod
    def _validate_binding(
        execution_request: ExecutionRequest,
        implementation_request: ImplementationRequest,
    ) -> None:
        expected = implementation_request.execution_request(
            idempotency_key=execution_request.idempotency_key
        )
        for field_name in (
            "request_id",
            "agent_identity",
            "action",
            "resource",
            "context_packet_id",
            "parameters",
        ):
            if getattr(execution_request, field_name) != getattr(expected, field_name):
                raise ImplementationRequestBindingError(
                    f"execution {field_name} does not match the registered implementation request"
                )

    @staticmethod
    def _result_for(proposal: PatchProposal) -> AdapterResult:
        return AdapterResult(
            output=(
                ("changed_lines", str(proposal.changed_lines)),
                ("diff_sha256", proposal.diff_sha256),
                ("proposal_id", proposal.proposal_id),
                ("provider_id", proposal.provider_id),
                ("request_fingerprint", proposal.request_fingerprint),
                ("touched_paths", ",".join(proposal.touched_paths)),
            )
        )
