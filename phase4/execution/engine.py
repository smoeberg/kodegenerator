"""Fail-closed AI-4 execution engine."""
from __future__ import annotations

from datetime import datetime, timezone
from threading import RLock
from typing import Dict, Tuple

from phase4.authority.models import AuthorityDecision, Decision

from .adapters import ExecutionAdapter
from .models import ExecutionRequest, ExecutionResult, ExecutionStatus, execution_id_for


class ExecutionError(Exception):
    """Base class for AI-4 execution errors."""


class ExecutionRejected(ExecutionError):
    """Raised by callers for malformed execution input when desired."""


class ExecutionEngine:
    """Execute only work covered by an explicit AI-3 ALLOW decision.

    AI-4 never evaluates policy and never turns a capability claim into
    authority. Only an explicit AI-3 ALLOW can reach an adapter.
    """

    def __init__(self, adapters: Tuple[ExecutionAdapter, ...] = ()) -> None:
        self._adapters: Dict[str, ExecutionAdapter] = {}
        self._results: Dict[str, ExecutionResult] = {}
        self._audit: list[ExecutionResult] = []
        self._lock = RLock()
        for adapter in adapters:
            self.register_adapter(adapter)

    def register_adapter(self, adapter: ExecutionAdapter) -> None:
        """Register a trusted adapter explicitly; duplicate actions are rejected."""
        adapter_id = adapter.adapter_id
        action = adapter.action
        if not adapter_id.strip() or not action.strip():
            raise ValueError("adapter_id and action must be non-empty")
        with self._lock:
            if action in self._adapters:
                raise ValueError(f"an adapter is already registered for action {action!r}")
            self._adapters[action] = adapter

    def execute(
        self,
        request: ExecutionRequest,
        authority_decision: AuthorityDecision | None,
    ) -> ExecutionResult:
        """Execute a request only when AI-3 has explicitly allowed that request."""
        if authority_decision is None:
            return self._rejected(request, "missing authority decision")

        mismatch = self._binding_error(request, authority_decision)
        if mismatch is not None:
            return self._rejected(request, mismatch, decision=authority_decision)

        # DENY is checked before idempotency lookup: a later denial must never
        # replay an earlier success for the same request.
        if authority_decision.decision is not Decision.ALLOW:
            return self._rejected(
                request,
                "authority decision is not ALLOW; execution denied",
                decision=authority_decision,
            )

        execution_id = execution_id_for(request, authority_decision)
        with self._lock:
            previous = self._results.get(execution_id)
            if previous is not None:
                replay = ExecutionResult(
                    execution_id=previous.execution_id,
                    request_id=previous.request_id,
                    authority_policy_id=previous.authority_policy_id,
                    authority_policy_version=previous.authority_policy_version,
                    agent_identity=previous.agent_identity,
                    action=previous.action,
                    resource=previous.resource,
                    context_packet_id=previous.context_packet_id,
                    status=ExecutionStatus.REPLAYED,
                    adapter_id=previous.adapter_id,
                    output=previous.output,
                    error="idempotent replay; adapter was not invoked again",
                    executed_at=datetime.now(timezone.utc).isoformat(),
                )
                self._audit.append(replay)
                return replay

            adapter = self._adapters.get(request.action)
            if adapter is None:
                return self._rejected(
                    request,
                    f"no execution adapter registered for action {request.action!r}",
                    decision=authority_decision,
                )

            try:
                adapter_result = adapter.execute(request)
                result = ExecutionResult(
                    execution_id=execution_id,
                    request_id=request.request_id,
                    authority_policy_id=authority_decision.policy_id,
                    authority_policy_version=authority_decision.policy_version,
                    agent_identity=request.agent_identity,
                    action=request.action,
                    resource=request.resource,
                    context_packet_id=request.context_packet_id,
                    status=ExecutionStatus.SUCCEEDED,
                    adapter_id=adapter.adapter_id,
                    output=adapter_result.output,
                    error=None,
                    executed_at=datetime.now(timezone.utc).isoformat(),
                )
            except Exception as exc:
                result = ExecutionResult(
                    execution_id=execution_id,
                    request_id=request.request_id,
                    authority_policy_id=authority_decision.policy_id,
                    authority_policy_version=authority_decision.policy_version,
                    agent_identity=request.agent_identity,
                    action=request.action,
                    resource=request.resource,
                    context_packet_id=request.context_packet_id,
                    status=ExecutionStatus.FAILED,
                    adapter_id=adapter.adapter_id,
                    output=(),
                    error=f"{type(exc).__name__}: {exc}",
                    executed_at=datetime.now(timezone.utc).isoformat(),
                )

            self._results[execution_id] = result
            self._audit.append(result)
            return result

    def audit_trail(self) -> Tuple[ExecutionResult, ...]:
        """Return an immutable snapshot of execution records."""
        with self._lock:
            return tuple(self._audit)

    def _rejected(
        self,
        request: ExecutionRequest,
        reason: str,
        *,
        decision: AuthorityDecision | None = None,
    ) -> ExecutionResult:
        policy_id = decision.policy_id if decision is not None else "none"
        policy_version = decision.policy_version if decision is not None else "none"
        execution_id = (
            execution_id_for(request, decision)
            if decision is not None
            else "rejected:" + request.request_id
        )
        result = ExecutionResult(
            execution_id=execution_id,
            request_id=request.request_id,
            authority_policy_id=policy_id,
            authority_policy_version=policy_version,
            agent_identity=request.agent_identity,
            action=request.action,
            resource=request.resource,
            context_packet_id=request.context_packet_id,
            status=ExecutionStatus.REJECTED,
            adapter_id="none",
            output=(),
            error=reason,
            executed_at=datetime.now(timezone.utc).isoformat(),
        )
        with self._lock:
            self._audit.append(result)
        return result

    @staticmethod
    def _binding_error(
        request: ExecutionRequest, decision: AuthorityDecision
    ) -> str | None:
        if decision.request_id != request.request_id:
            return "request ID does not match the authority decision"
        if decision.agent_identity != request.agent_identity:
            return "agent identity does not match the authority decision"
        if decision.action != request.action:
            return "action does not match the authority decision"
        if decision.resource != request.resource:
            return "resource does not match the authority decision"
        if decision.context_packet_id != request.context_packet_id:
            return "context packet does not match the authority decision"
        return None
