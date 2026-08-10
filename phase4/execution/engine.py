"""Fail-closed AI-4 execution engine."""
from __future__ import annotations

from datetime import datetime, timezone
from threading import RLock
from typing import Dict, Tuple

from phase4.authority.grants import VerifiedAuthorityGrant
from phase4.authority.models import AuthorityDecision, Decision

from .adapters import ExecutionAdapter
from .models import (
    ExecutionRequest,
    ExecutionResult,
    ExecutionStatus,
    GovernedDispatch,
    execution_id_for,
)


class ExecutionError(Exception):
    """Base class for AI-4 execution errors."""


class ExecutionRejected(ExecutionError):
    """Raised by callers for malformed execution input when desired."""


class ExecutionEngine:
    """Execute only work covered by a verified AI-3 authority grant."""

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
        authority: AuthorityDecision | VerifiedAuthorityGrant | None,
    ) -> ExecutionResult:
        """Execute only work covered by a verified AI-3 grant."""
        if authority is None:
            return self._rejected(request, "missing authority decision")

        if isinstance(authority, VerifiedAuthorityGrant):
            grant = authority
            decision = None
        elif isinstance(authority, AuthorityDecision):
            # Provenance is checked independently of ALLOW/DENY. A genuine AI-3
            # DENY must reach the normal authorization branch so callers receive
            # the semantic "not ALLOW" rejection rather than a provenance error.
            if getattr(authority, "_provenance_token", None) is None:
                return self._rejected(
                    request,
                    "authority decision provenance is invalid or untrusted",
                    decision=authority,
                )
            decision = authority
            if decision.decision is not Decision.ALLOW:
                return self._rejected(
                    request,
                    "authority decision is not ALLOW; execution denied",
                    decision=decision,
                )
            try:
                grant = VerifiedAuthorityGrant.from_decision(decision)
            except ValueError:
                return self._rejected(
                    request,
                    "authority decision provenance is invalid or untrusted",
                    decision=decision,
                )
        else:
            return self._rejected(request, "unsupported authority credential")

        if not grant.binds(request):
            return self._rejected(
                request,
                "authority grant is not bound to the execution request",
                decision=decision,
            )

        if grant.decision != Decision.ALLOW.value:
            return self._rejected(
                request,
                "authority decision is not ALLOW; execution denied",
                decision=decision,
            )

        if decision is None:
            decision = AuthorityDecision(
                request_id=grant.request_id,
                decision=Decision.ALLOW,
                agent_identity=grant.agent_identity,
                action=grant.action,
                resource=grant.resource,
                context_packet_id=grant.context_packet_id,
                policy_id=grant.policy_id,
                policy_version=grant.policy_version,
                matched_rule_ids=grant.matched_rule_ids,
                reason="verified AI-3 authority grant",
                evaluated_at="verified-grant",
            )
        dispatch = GovernedDispatch.issue(request, grant)
        execution_id = execution_id_for(request, decision)

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
                    decision=decision,
                )

            try:
                adapter_result = adapter.execute(request, dispatch=dispatch)
                if adapter_result is None:
                    return self._rejected(
                        request,
                        "adapter rejected execution without a verified governed dispatch",
                        decision=decision,
                    )
                result = ExecutionResult(
                    execution_id=execution_id,
                    request_id=request.request_id,
                    authority_policy_id=decision.policy_id,
                    authority_policy_version=decision.policy_version,
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
                    authority_policy_id=decision.policy_id,
                    authority_policy_version=decision.policy_version,
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
