"""Fail-closed AI-4 execution engine."""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from threading import RLock

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
from .replay_ledger import ClaimOutcomeKind, ExecutionReplayLedger, InMemoryReplayLedger

logger = logging.getLogger(__name__)

class ExecutionError(Exception): pass
class ExecutionRejected(ExecutionError): pass

class ExecutionEngine:
    def __init__(self, adapters: tuple[ExecutionAdapter, ...] = (), ledger: ExecutionReplayLedger | None = None) -> None:
        self._adapters: dict[str, ExecutionAdapter] = {}
        self._ledger = ledger or InMemoryReplayLedger()
        self._audit: list[ExecutionResult] = []
        self._lock = RLock()
        for adapter in adapters: self.register_adapter(adapter)

    def register_adapter(self, adapter: ExecutionAdapter) -> None:
        if not adapter.adapter_id.strip() or not adapter.action.strip(): raise ValueError("adapter_id and action must be non-empty")
        with self._lock:
            if adapter.action in self._adapters: raise ValueError(f"an adapter is already registered for action {adapter.action!r}")
            self._adapters[adapter.action] = adapter

    def execute(self, request: ExecutionRequest, authority: AuthorityDecision | VerifiedAuthorityGrant | None) -> ExecutionResult:
        if not isinstance(request, ExecutionRequest): return self._rejected(request, "unsupported execution request")
        # AI-4 accepts only a verified AI-3 grant. A raw AuthorityDecision is
        # deliberately rejected even when it appears internally valid: callers
        # must cross the explicit provenance-bearing grant boundary.
        if not isinstance(authority, VerifiedAuthorityGrant):
            return self._rejected(request, "missing authority: execution requires a verified authority grant")
        grant = authority
        if not grant.binds(request): return self._rejected(request, "authority grant is not bound to the execution request")
        if grant.decision != Decision.ALLOW.value: return self._rejected(request, "authority decision is not ALLOW; execution denied")
        decision = AuthorityDecision(request_id=grant.request_id, decision=Decision.ALLOW, agent_identity=grant.agent_identity, action=grant.action, resource=grant.resource, context_packet_id=grant.context_packet_id, policy_id=grant.policy_id, policy_version=grant.policy_version, matched_rule_ids=grant.matched_rule_ids, reason="verified AI-3 authority grant", evaluated_at="verified-grant", parameters=grant.parameters, organization_id=grant.organization_id, actor_id=grant.actor_id, capability=grant.capability)
        dispatch = GovernedDispatch.issue(request, grant)
        execution_id = execution_id_for(request, decision)
        adapter=self._adapters.get(request.action)
        if adapter is None:
            return self._rejected(request, "no execution adapter registered for action", decision=decision)
        claim = self._ledger.try_claim(execution_id, grant_id=grant.grant_id, request_id=request.request_id)
        if claim.kind is ClaimOutcomeKind.ALREADY_SUCCEEDED:
            previous=claim.record.result if claim.record else None
            if previous is None: return self._rejected(request,"successful replay has no stored result",decision=decision)
            return self._replay(previous)
        if claim.kind is ClaimOutcomeKind.IN_FLIGHT: return self._rejected(request,"execution already in flight for this execution_id",decision=decision)
        token=claim.record.fencing_token if claim.record else None
        if not token: return self._rejected(request,"acquired claim missing fencing token",decision=decision)
        try:
            adapter_result=adapter.execute(request, dispatch=dispatch)
            if adapter_result is None: result=self._failed(request,execution_id,decision,"adapter rejected execution without a verified governed dispatch")
            else: result=ExecutionResult(execution_id=execution_id,request_id=request.request_id,authority_policy_id=decision.policy_id,authority_policy_version=decision.policy_version,agent_identity=request.agent_identity,action=request.action,resource=request.resource,context_packet_id=request.context_packet_id,status=ExecutionStatus.SUCCEEDED,adapter_id=adapter.adapter_id,output=adapter_result.output,error=None,executed_at=datetime.now(timezone.utc).isoformat())
        except Exception as exc:
            result=self._failed(request,execution_id,decision,f"{type(exc).__name__}: {exc}")
        try:
            if result.status is ExecutionStatus.SUCCEEDED: self._ledger.complete_succeeded(execution_id,result,fencing_token=token)
            else: self._ledger.complete_failed(execution_id,result,fencing_token=token)
        except Exception:
            try:
                self._ledger.abandon(execution_id, fencing_token=token)
            except Exception:
                logger.exception(
                    "failed to abandon execution claim after terminal ledger error",
                    extra={"execution_id": execution_id},
                )
            raise
        with self._lock: self._audit.append(result)
        return result

    def _replay(self, previous: ExecutionResult) -> ExecutionResult:
        replay=ExecutionResult(execution_id=previous.execution_id,request_id=previous.request_id,authority_policy_id=previous.authority_policy_id,authority_policy_version=previous.authority_policy_version,agent_identity=previous.agent_identity,action=previous.action,resource=previous.resource,context_packet_id=previous.context_packet_id,status=ExecutionStatus.REPLAYED,adapter_id=previous.adapter_id,output=previous.output,error="idempotent replay; adapter was not invoked again",executed_at=datetime.now(timezone.utc).isoformat())
        with self._lock: self._audit.append(replay)
        return replay

    def _failed(self, request, execution_id, decision, error):
        return ExecutionResult(execution_id=execution_id,request_id=request.request_id,authority_policy_id=decision.policy_id,authority_policy_version=decision.policy_version,agent_identity=request.agent_identity,action=request.action,resource=request.resource,context_packet_id=request.context_packet_id,status=ExecutionStatus.FAILED,adapter_id=getattr(self._adapters.get(request.action),"adapter_id","none"),output=(),error=error,executed_at=datetime.now(timezone.utc).isoformat())

    def _rejected(self, request, reason, *, decision=None):
        execution_id=execution_id_for(request,decision) if decision is not None else "rejected:"+getattr(request,"request_id","unknown")
        result=ExecutionResult(execution_id=execution_id,request_id=request.request_id,authority_policy_id=decision.policy_id if decision else "none",authority_policy_version=decision.policy_version if decision else "none",agent_identity=getattr(request,"agent_identity","unknown"),action=getattr(request,"action","unknown"),resource=getattr(request,"resource","unknown"),context_packet_id=getattr(request,"context_packet_id","unknown"),status=ExecutionStatus.REJECTED,adapter_id="none",output=(),error=reason,executed_at=datetime.now(timezone.utc).isoformat())
        with self._lock: self._audit.append(result)
        return result

    def audit_trail(self) -> tuple[ExecutionResult, ...]:
        with self._lock: return tuple(self._audit)
