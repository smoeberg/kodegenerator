"""Governed AI-3 through AI-5 runtime for validated patch application."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from threading import RLock

from phase4.authority import AuthorityDecision, AuthorityEngine, AuthorityPolicy, AuthorityRule, Decision
from phase4.authority.grants import VerifiedAuthorityGrant
from phase4.execution import ExecutionEngine, ExecutionResult, ExecutionStatus
from phase4.execution.models import ExecutionRequest, GovernedDispatch
from phase4.outcome.engine import OutcomeEngine
from phase4.outcome.models import OutcomeRecord, OutcomeStatus

from .adapter import PatchProposalNotFoundError
from .patch_adapter import PatchExecutionAdapter, PatchExecutionRequestNotFoundError, ToolRunner, WorkspacePatchExecutor
from .patch_models import IMPLEMENTATION_APPLY_ACTION, PatchExecutionRecord, PatchExecutionRequest, TrustedToolSpec
from .runtime import ImplementationAgentRuntime
from .sandbox_tool_runner import BubblewrapToolRunner


class GovernedPatchRuntimeError(RuntimeError):
    """Base error for the governed patch-execution runtime."""


class GovernedPatchAuthorityError(GovernedPatchRuntimeError):
    """AI-3 denied the exact authority-bound patch application."""

    def __init__(self, decision: AuthorityDecision) -> None:
        self.decision = decision
        super().__init__("AI-3 denied the governed patch-execution request")


class GovernedPatchCommandConflictError(GovernedPatchRuntimeError):
    """A command ID was reused for a different proposal."""


class GovernedPatchExecutionError(GovernedPatchRuntimeError):
    """AI-4/AI-5 did not produce a retrievable patch-execution record."""

    def __init__(self, execution: ExecutionResult, outcome: OutcomeRecord) -> None:
        self.execution = execution
        self.outcome = outcome
        super().__init__("governed patch execution produced no usable record")


@dataclass(frozen=True)
class GovernedPatchRun:
    """Patch attempt plus exact AI-3, AI-4 and AI-5 provenance."""

    agent_identity: str
    request: PatchExecutionRequest
    authority: AuthorityDecision
    execution: ExecutionResult
    outcome: OutcomeRecord
    record: PatchExecutionRecord

    @property
    def replayed(self) -> bool:
        return self.execution.status is ExecutionStatus.REPLAYED


class _GovernedPatchAdapter:
    """Execution seam that makes the patch adapter dispatch-bound."""

    def __init__(self, adapter: PatchExecutionAdapter) -> None:
        self._adapter = adapter

    @property
    def adapter_id(self) -> str:
        return self._adapter.adapter_id

    @property
    def action(self) -> str:
        return self._adapter.action

    def register_request(self, request: PatchExecutionRequest) -> None:
        self._adapter.register_request(request)

    def execute(self, request: ExecutionRequest, *, dispatch: GovernedDispatch | None = None):
        if not isinstance(dispatch, GovernedDispatch):
            return None
        if not dispatch.is_verified or dispatch.request is not request:
            return None
        return self._adapter.execute(request)

    def get_record(self, request_fingerprint: str) -> PatchExecutionRecord:
        return self._adapter.get_record(request_fingerprint)


class GovernedPatchExecutionRuntime:
    """Apply only stored proposals through operator-fixed tools and AI-3 authority."""

    def __init__(self, *, proposal_runtime: ImplementationAgentRuntime, workspace_root: Path, tools: tuple[TrustedToolSpec, ...], tool_runner: ToolRunner | None = None, max_file_bytes: int = 16 * 1024 * 1024, max_workspace_files: int = 20_000, max_workspace_bytes: int = 256 * 1024 * 1024, patch_timeout_seconds: int = 30) -> None:
        if not isinstance(proposal_runtime, ImplementationAgentRuntime):
            raise TypeError("proposal_runtime must be an ImplementationAgentRuntime")
        if not isinstance(tools, tuple) or any(not isinstance(tool, TrustedToolSpec) for tool in tools):
            raise TypeError("tools must be a tuple of TrustedToolSpec values")
        if not tools:
            raise ValueError("governed patch execution requires trusted tools")
        self._proposal_runtime = proposal_runtime
        self._tools = tools
        effective_tool_runner = tool_runner if tool_runner is not None else BubblewrapToolRunner()
        self._workspace = WorkspacePatchExecutor(workspace_root, tool_runner=effective_tool_runner, max_file_bytes=max_file_bytes, max_workspace_files=max_workspace_files, max_workspace_bytes=max_workspace_bytes, patch_timeout_seconds=patch_timeout_seconds)
        self._authority = AuthorityEngine(self._policy_for())
        self._adapter = PatchExecutionAdapter(adapter_id="adapter.implementation.governed-patch", workspace=self._workspace)
        self._governed_adapter = _GovernedPatchAdapter(self._adapter)
        self._execution = ExecutionEngine((self._governed_adapter,))
        self._outcomes = OutcomeEngine()
        self._commands: dict[str, tuple[str, PatchExecutionRequest]] = {}
        self._lock = RLock()

    @property
    def tools(self) -> tuple[TrustedToolSpec, ...]:
        return self._tools

    @property
    def workspace_root(self) -> Path:
        return self._workspace.root

    def run(self, *, proposal_id: str, idempotency_key: str) -> GovernedPatchRun:
        for name, value in (("proposal_id", proposal_id), ("idempotency_key", idempotency_key)):
            if not isinstance(value, str) or not value.strip() or value != value.strip():
                raise ValueError(f"{name} must be a canonical non-empty string")
        proposal = self._proposal_runtime.get_proposal(proposal_id)
        if proposal.request.resource not in self._proposal_runtime.allowed_resources:
            raise GovernedPatchRuntimeError("proposal resource is outside the operator-configured runtime scope")
        agent_identity = str(self._proposal_runtime.agent.identity)
        if proposal.request.agent_identity != agent_identity:
            raise GovernedPatchRuntimeError("proposal agent identity does not match the registered runtime agent")
        with self._lock:
            bound = self._commands.get(idempotency_key)
            if bound is not None:
                bound_proposal_id, request = bound
                if bound_proposal_id != proposal_id:
                    raise GovernedPatchCommandConflictError("idempotency key is already bound to another proposal")
            else:
                request = PatchExecutionRequest(proposal=proposal, baseline=self._workspace.observe(proposal), tools=self._tools)
                self._commands[idempotency_key] = (proposal_id, request)
                self._adapter.register_request(request)
            authority = self._authority.evaluate(request.authority_request())
            if not authority.allowed:
                raise GovernedPatchAuthorityError(authority)
            grant = VerifiedAuthorityGrant.from_decision(authority)
            execution = self._execution.execute(request.execution_request(idempotency_key=idempotency_key), grant)
            outcome = self._outcomes.process(execution)
            if execution.status is ExecutionStatus.REJECTED or outcome.status in {OutcomeStatus.REJECTED, OutcomeStatus.UNKNOWN}:
                raise GovernedPatchExecutionError(execution, outcome)
            try:
                record = self._adapter.get_record(request.request_fingerprint)
            except PatchExecutionRequestNotFoundError as exc:
                raise GovernedPatchExecutionError(execution, outcome) from exc
            return GovernedPatchRun(agent_identity=agent_identity, request=request, authority=authority, execution=execution, outcome=outcome, record=record)

    def authority_audit(self) -> tuple[AuthorityDecision, ...]:
        return self._authority.audit_trail()

    def execution_audit(self) -> tuple[ExecutionResult, ...]:
        return self._execution.audit_trail()

    def _policy_for(self) -> AuthorityPolicy:
        agent = self._proposal_runtime.agent
        rules = tuple(AuthorityRule(rule_id="allow-governed-patch-execution-" + hashlib.sha256(resource.encode("utf-8")).hexdigest()[:16], action=IMPLEMENTATION_APPLY_ACTION, resource_pattern=resource, effect=Decision.ALLOW, agent_identity=str(agent.identity), agent_role=agent.role.value) for resource in self._proposal_runtime.allowed_resources)
        return AuthorityPolicy(policy_id="policy.implementation-agent.patch-execution", version="1", rules=rules)


__all__ = ["GovernedPatchAuthorityError", "GovernedPatchCommandConflictError", "GovernedPatchExecutionError", "GovernedPatchExecutionRuntime", "GovernedPatchRun", "GovernedPatchRuntimeError", "PatchProposalNotFoundError"]
