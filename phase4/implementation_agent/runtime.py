"""Operational AI-1 through AI-5 runtime for bounded patch proposals."""

from __future__ import annotations

import hashlib
from collections.abc import Iterable
from dataclasses import dataclass
from threading import RLock

from phase4.agent_registry import AgentRecord, AgentRegistry, AgentRole, AgentVersion, Capability
from phase4.authority import AuthorityDecision, AuthorityEngine, AuthorityPolicy, AuthorityRule, Decision, VerifiedAuthorityGrant
from phase4.context_packet import ContextItem, ContextPacket, ContextPacketEngine, ContextRequest
from phase4.execution import ExecutionEngine, ExecutionResult, ExecutionStatus
from phase4.outcome.engine import OutcomeEngine
from phase4.outcome.models import OutcomeRecord, OutcomeStatus

from .adapter import ImplementationExecutionAdapter, ImplementationProvider
from .models import IMPLEMENTATION_ACTION, ChangeBudget, ImplementationRequest, PatchProposal
from .patch_models import IMPLEMENTATION_APPLY_ACTION


class ImplementationAgentRuntimeError(RuntimeError): pass
class ImplementationAgentAuthorityError(ImplementationAgentRuntimeError):
    def __init__(self, decision: AuthorityDecision) -> None:
        self.decision = decision
        super().__init__("AI-3 denied the implementation-agent request")
class ImplementationAgentExecutionError(ImplementationAgentRuntimeError):
    def __init__(self, execution: ExecutionResult, outcome: OutcomeRecord) -> None:
        self.execution, self.outcome = execution, outcome
        super().__init__("implementation-agent execution did not succeed")
class ImplementationCommandConflictError(ImplementationAgentRuntimeError): pass
class ImplementationContextLimitError(ImplementationAgentRuntimeError): pass


@dataclass(frozen=True)
class ImplementationAgentRun:
    agent_identity: str
    context_packet: ContextPacket
    request: ImplementationRequest
    authority: AuthorityDecision
    authority_grant: VerifiedAuthorityGrant
    execution: ExecutionResult
    outcome: OutcomeRecord
    proposal: PatchProposal
    @property
    def replayed(self) -> bool:
        return self.execution.status is ExecutionStatus.REPLAYED


class ImplementationAgentRuntime:
    def __init__(self, *, provider: ImplementationProvider, allowed_resources: Iterable[str], max_files: int = 8, max_changed_lines: int = 1_000, max_context_items: int = 200, max_context_bytes: int = 512 * 1024) -> None:
        provider_id = getattr(provider, "provider_id", None)
        if not isinstance(provider_id, str) or not provider_id.strip(): raise ValueError("provider must declare a non-empty provider_id")
        if not callable(getattr(provider, "propose_patch", None)): raise TypeError("provider must implement propose_patch")
        resources = tuple(sorted(set(allowed_resources)))
        if not resources: raise ValueError("allowed_resources must not be empty")
        for resource in resources:
            if not isinstance(resource, str) or not resource.strip() or resource != resource.strip() or any(c in resource for c in "*?["):
                raise ValueError("allowed resources must be canonical exact strings without globs")
        for name, value in (("max_files", max_files), ("max_changed_lines", max_changed_lines), ("max_context_items", max_context_items), ("max_context_bytes", max_context_bytes)):
            if type(value) is not int or value < 1: raise ValueError(f"{name} must be a positive integer")
        self._allowed_resources, self._max_files, self._max_changed_lines = resources, max_files, max_changed_lines
        self._max_context_items, self._max_context_bytes = max_context_items, max_context_bytes
        self._context = ContextPacketEngine(); self._registry = AgentRegistry(); self._agent = self._register_agent(provider_id)
        self._authority = AuthorityEngine(self._policy_for(resources)); self._adapter = ImplementationExecutionAdapter(adapter_id=f"adapter.implementation.runtime:{provider_id}", provider=provider)
        self._execution = ExecutionEngine((self._adapter,)); self._outcomes = OutcomeEngine(); self._registered_requests: set[str] = set(); self._commands: dict[str, str] = {}; self._lock = RLock()

    @property
    def agent(self) -> AgentRecord: return self._agent
    @property
    def allowed_resources(self) -> tuple[str, ...]: return self._allowed_resources

    def run(self, *, organization_id: str, resource: str, instruction: str, allowed_paths: tuple[str, ...], context_items: Iterable[ContextItem], budget: ChangeBudget, idempotency_key: str) -> ImplementationAgentRun:
        if not isinstance(organization_id, str) or not organization_id.strip(): raise ValueError("organization_id must be a non-empty string")
        if not isinstance(resource, str) or not resource.strip() or resource != resource.strip() or any(c in resource for c in "*?["): raise ValueError("resource must be a canonical exact string without globs")
        if not isinstance(budget, ChangeBudget): raise TypeError("budget must be a ChangeBudget")
        if budget.max_files > self._max_files: raise ValueError("request exceeds the runtime file budget")
        if budget.max_changed_lines > self._max_changed_lines: raise ValueError("request exceeds the runtime changed-line budget")
        if not isinstance(idempotency_key, str) or not idempotency_key.strip() or idempotency_key != idempotency_key.strip(): raise ValueError("idempotency_key must be a canonical non-empty string")
        items = tuple(context_items)
        if not items: raise ValueError("context_items must not be empty")
        if any(not isinstance(item, ContextItem) for item in items): raise TypeError("context_items must contain ContextItem values")
        if any(item.sensitivity == "sensitive" for item in items): raise ValueError("sensitive context requires an explicit future operator policy")
        packet = self._context.build(ContextRequest(agent_identity=str(self._agent.identity), purpose=IMPLEMENTATION_ACTION, requested_keys=tuple(sorted({item.key for item in items})), max_items=self._max_context_items, max_bytes=self._max_context_bytes), items, actor="implementation-agent-runtime")
        if packet.truncated: raise ImplementationContextLimitError("eligible implementation context exceeds runtime bounds")
        request = ImplementationRequest(organization_id=organization_id, agent_identity=str(self._agent.identity), agent_role=self._agent.role.value, resource=resource, context_packet=packet, instruction=instruction, allowed_paths=allowed_paths, budget=budget)
        self._bind_command(idempotency_key, request.request_fingerprint)
        authority = self._authority.evaluate(request.authority_request())
        if not authority.allowed: raise ImplementationAgentAuthorityError(authority)
        authority_grant = VerifiedAuthorityGrant.from_decision(authority)
        self._register_request_once(request)
        execution = self._execution.execute(request.execution_request(idempotency_key=idempotency_key), authority_grant)
        outcome = self._outcomes.process(execution)
        if execution.status not in {ExecutionStatus.SUCCEEDED, ExecutionStatus.REPLAYED} or outcome.status not in {OutcomeStatus.SUCCEEDED, OutcomeStatus.REPLAYED}: raise ImplementationAgentExecutionError(execution, outcome)
        proposal_id = dict(execution.output).get("proposal_id")
        if proposal_id is None: raise ImplementationAgentExecutionError(execution, outcome)
        proposal = self._adapter.get_proposal(proposal_id)
        if proposal.request_fingerprint != request.request_fingerprint: raise ImplementationAgentExecutionError(execution, outcome)
        return ImplementationAgentRun(str(self._agent.identity), packet, request, authority, authority_grant, execution, outcome, proposal)

    def authority_audit(self) -> tuple[AuthorityDecision, ...]: return self._authority.audit_trail()
    def execution_audit(self) -> tuple[ExecutionResult, ...]: return self._execution.audit_trail()
    def get_proposal(self, proposal_id: str) -> PatchProposal: return self._adapter.get_proposal(proposal_id)

    def _register_agent(self, provider_id: str) -> AgentRecord:
        version = AgentVersion(1, 2, 0)
        return self._registry.register(agent_type="implementation-agent", version=version, role=AgentRole.EXECUTOR, capabilities=(Capability.create(IMPLEMENTATION_ACTION, version, parameters={"provider": provider_id, "mode": "bounded-patch-proposal"}), Capability.create(IMPLEMENTATION_APPLY_ACTION, version, parameters={"mode": "governed-patch-execution"})), actor="implementation-agent-runtime")

    def _policy_for(self, resources: tuple[str, ...]) -> AuthorityPolicy:
        return AuthorityPolicy(policy_id="policy.implementation-agent.runtime", version="1", rules=tuple(AuthorityRule(rule_id="allow-bounded-implementation-proposal-" + hashlib.sha256(resource.encode()).hexdigest()[:16], action=IMPLEMENTATION_ACTION, resource_pattern=resource, effect=Decision.ALLOW, agent_identity=str(self._agent.identity), agent_role=self._agent.role.value) for resource in resources))

    def _bind_command(self, idempotency_key: str, request_fingerprint: str) -> None:
        with self._lock:
            existing = self._commands.get(idempotency_key)
            if existing is not None and existing != request_fingerprint: raise ImplementationCommandConflictError("idempotency key is already bound to another request")
            self._commands[idempotency_key] = request_fingerprint

    def _register_request_once(self, request: ImplementationRequest) -> None:
        with self._lock:
            if request.request_fingerprint in self._registered_requests: return
            self._adapter.register_request(request); self._registered_requests.add(request.request_fingerprint)
