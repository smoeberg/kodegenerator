"""Fail-closed AI-4 execution engine."""
from __future__ import annotations

from datetime import datetime, timezone
from threading import RLock
from typing import Dict, Optional, Tuple

from phase4.authority.grants import VerifiedAuthorityGrant
from phase4.authority.models import AuthorityDecision, Decision

from .adapters import ExecutionAdapter
from .ledger import (
    ClaimResult,
    ExecutionLedger,
    InProcessLedger,
    PendingClaimOutcome,
    ReplayPolicy,
)
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
    """Execute only work covered by a verified AI-3 authority grant.

    A durable replay ``ledger`` (P4-01) may be supplied to enforce single
    execution of an ``execution_id`` across engine instances (restarts,
    workers, nodes). Without a ledger the legacy in-process replay store is
    used, which is not durable and not shared across processes.
    """

    def __init__(
        self,
        adapters: Tuple[ExecutionAdapter, ...] = (),
        *,
        ledger: Optional[ExecutionLedger] = None,
        replay_policy: Optional[ReplayPolicy] = None,
    ) -> None:
        self._adapters: Dict[str, ExecutionAdapter] = {}
        self._results: Dict[str, ExecutionResult] = {}
        self._audit: list[ExecutionResult] = []
        self._lock = RLock()
        self._ledger: Optional[ExecutionLedger] = ledger
        self._replay_policy: ReplayPolicy = replay_policy or ReplayPolicy()
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
        authority: VerifiedAuthorityGrant | AuthorityDecision | None,
    ) -> ExecutionResult:
        """Execute only work covered by a verified AI-3 grant.

        A raw ``AuthorityDecision`` is deliberately not accepted here. Even a
        genuine decision carries policy provenance, not an execution capability.
        Only ``VerifiedAuthorityGrant`` may cross the AI-3 -> AI-4 boundary.
        """
        if authority is None:
            return self._rejected(request, "missing authority decision")

        if not isinstance(authority, VerifiedAuthorityGrant):
            return self._rejected(
                request,
                "execution requires a VerifiedAuthorityGrant; raw authority decisions are not executable",
            )

        grant = authority
        if not grant.verified:
            return self._rejected(request, "authority grant provenance is invalid or untrusted")

        if not grant.binds(request):
            return self._rejected(
                request,
                "authority grant is not bound to the execution request",
            )

        if grant.decision != Decision.ALLOW.value:
            return self._rejected(
                request,
                "authority decision is not ALLOW; execution denied",
            )

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
            parameters=grant.parameters,
            organization_id=grant.organization_id,
            actor_id=grant.actor_id,
            capability=grant.capability,
        )
        dispatch = GovernedDispatch.issue(request, grant)
        execution_id = execution_id_for(request, decision)

        # P4-01: when a durable ledger is configured, claim the execution_id
        # atomically before invoking the adapter. This blocks RA-1 (restart),
        # RA-2 (multi-worker), RA-3 (crash during adapter), and RA-4 (cross-node
        # replay of a leaked genuine grant).
        if self._ledger is not None:
            return self._execute_with_ledger(request, grant, decision, dispatch, execution_id)

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

            result = self._run_adapter(request, decision, dispatch, execution_id, adapter)
            self._results[execution_id] = result
            self._audit.append(result)
            return result

    def _execute_with_ledger(
        self,
        request: ExecutionRequest,
        grant: VerifiedAuthorityGrant,
        decision: AuthorityDecision,
        dispatch: GovernedDispatch,
        execution_id: str,
    ) -> ExecutionResult:
        """Claim, run the adapter once, and complete against the durable ledger."""
        assert self._ledger is not None  # narrowed by caller
        started_at = datetime.now(timezone.utc).isoformat()
        claim, existing = self._ledger.claim(
            execution_id,
            request_id=request.request_id,
            grant_id=getattr(grant, "grant_id", ""),
            authority_policy_id=decision.policy_id,
            authority_policy_version=decision.policy_version,
            started_at=started_at,
        )

        if claim is ClaimResult.REPLAYED and existing is not None:
            replay = ExecutionResult(
                execution_id=existing.execution_id,
                request_id=existing.request_id,
                authority_policy_id=existing.authority_policy_id,
                authority_policy_version=existing.authority_policy_version,
                agent_identity=request.agent_identity,
                action=request.action,
                resource=request.resource,
                context_packet_id=request.context_packet_id,
                status=ExecutionStatus.REPLAYED,
                adapter_id=existing.adapter_id or "none",
                output=(),
                error="idempotent replay; adapter was not invoked again",
                executed_at=datetime.now(timezone.utc).isoformat(),
            )
            with self._lock:
                self._audit.append(replay)
            return replay

        if claim is ClaimResult.PENDING:
            # An in-flight execution exists. Apply the policy-driven behaviour.
            if self._replay_policy.pending_claim is PendingClaimOutcome.WAIT:
                terminal = self._ledger.wait_for_terminal(execution_id, timeout=5.0)
                if terminal is not None:
                    replay = ExecutionResult(
                        execution_id=terminal.execution_id,
                        request_id=terminal.request_id,
                        authority_policy_id=terminal.authority_policy_id,
                        authority_policy_version=terminal.authority_policy_version,
                        agent_identity=request.agent_identity,
                        action=request.action,
                        resource=request.resource,
                        context_packet_id=request.context_packet_id,
                        status=ExecutionStatus.REPLAYED,
                        adapter_id=terminal.adapter_id or "none",
                        output=(),
                        error="idempotent replay after pending wait; adapter not invoked",
                        executed_at=datetime.now(timezone.utc).isoformat(),
                    )
                    with self._lock:
                        self._audit.append(replay)
                    return replay
                # Timed out waiting: fail closed.
                return self._rejected(
                    request,
                    "execution is in flight and the pending wait timed out",
                    decision=decision,
                )
            return self._rejected(
                request,
                "execution is already in flight (pending claim)",
                decision=decision,
            )

        # ACQUIRED: this caller owns the execution and must run the adapter.
        with self._lock:
            adapter = self._adapters.get(request.action)
        if adapter is None:
            self._ledger.complete(
                execution_id,
                status=ExecutionStatus.FAILED,
                adapter_id="none",
                outcome_fingerprint=None,
                completed_at=datetime.now(timezone.utc).isoformat(),
                error=f"no execution adapter registered for action {request.action!r}",
            )
            return self._rejected(
                request,
                f"no execution adapter registered for action {request.action!r}",
                decision=decision,
            )

        result = self._run_adapter(request, decision, dispatch, execution_id, adapter)

        if result.status is ExecutionStatus.SUCCEEDED or result.status is ExecutionStatus.FAILED:
            self._ledger.complete(
                execution_id,
                status=result.status,
                adapter_id=result.adapter_id,
                outcome_fingerprint=None,
                completed_at=result.executed_at,
                error=result.error,
            )

        with self._lock:
            self._results[execution_id] = result
            self._audit.append(result)
        return result

    def _run_adapter(
        self,
        request: ExecutionRequest,
        decision: AuthorityDecision,
        dispatch: GovernedDispatch,
        execution_id: str,
        adapter: ExecutionAdapter,
    ) -> ExecutionResult:
        """Invoke the adapter once and build the result. Side effects only here."""
        try:
            adapter_result = adapter.execute(request, dispatch=dispatch)
            if adapter_result is None:
                return ExecutionResult(
                    execution_id=execution_id,
                    request_id=request.request_id,
                    authority_policy_id=decision.policy_id,
                    authority_policy_version=decision.policy_version,
                    agent_identity=request.agent_identity,
                    action=request.action,
                    resource=request.resource,
                    context_packet_id=request.context_packet_id,
                    status=ExecutionStatus.REJECTED,
                    adapter_id="none",
                    output=(),
                    error="adapter rejected execution without a verified governed dispatch",
                    executed_at=datetime.now(timezone.utc).isoformat(),
                )
            return ExecutionResult(
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
            return ExecutionResult(
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
