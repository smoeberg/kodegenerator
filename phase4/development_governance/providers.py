"""Provider-neutral Governance v0 role adapters.

These adapters only exchange schema-validated data through ``GovernedLLMRuntime``.
They grant no file-system, execution, approval, publication, or deployment authority.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import asdict
from enum import Enum
from pathlib import Path
from typing import Any, Protocol

from phase4.context_packet import ContextItem
from phase4.implementation_agent import (
    ChangeBudget,
    GovernedPatchExecutionRuntime,
    ImplementationAgentRuntime,
    PatchExecutionRequestNotFoundError,
)
from services.git_pr_publisher import GitWorktreeManager
from services.governed_llm import GovernedLLMRequest, GovernedLLMRuntime

from .contracts import (
    ArtifactSubmission,
    AuditDecision,
    EvidenceReport,
    IndependentReview,
    ProblemApproval,
    ProblemBrief,
    ProblemDecision,
    ReviewDecision,
    ScopeConformance,
    SolutionApproval,
    SolutionDecision,
    SolutionProposal,
)


def _json(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, tuple):
        return [_json(item) for item in value]
    if isinstance(value, dict):
        return {key: _json(item) for key, item in value.items()}
    if hasattr(value, "__dataclass_fields__"):
        return _json(asdict(value))
    return value


def _object_schema(properties: Mapping[str, Any], required: tuple[str, ...]) -> dict[str, Any]:
    return {
        "type": "object", "additionalProperties": False,
        "properties": dict(properties), "required": list(required),
    }


TEXT = {"type": "string", "minLength": 1}
TEXTS = {"type": "array", "items": TEXT, "uniqueItems": True}
BOOL = {"type": "boolean"}


class GovernedRoleAdapter:
    """Base for a single logical role bound to one governed LLM runtime."""

    def __init__(self, provider_id: str, runtime: GovernedLLMRuntime, *, organization_id: str,
                 model: str, max_input_tokens: int = 32_000, max_output_tokens: int = 8_000) -> None:
        if not isinstance(provider_id, str) or not provider_id.strip() or provider_id != provider_id.strip():
            raise ValueError("provider_id must be canonical non-empty text")
        self.provider_id = provider_id
        self._runtime = runtime
        self._organization_id = organization_id
        self._model = model
        self._max_input_tokens = max_input_tokens
        self._max_output_tokens = max_output_tokens

    def _call(self, purpose: str, inputs: Mapping[str, Any], schema: Mapping[str, Any], instructions: str) -> Mapping[str, Any]:
        result = self._runtime.generate(GovernedLLMRequest(
            organization_id=self._organization_id,
            actor_id=self.provider_id,
            idempotency_key=f"governance:{self.provider_id}:{purpose}:" + hashlib.sha256(
                json.dumps(_json(inputs), sort_keys=True, separators=(",", ":")).encode()
            ).hexdigest(),
            purpose=purpose, model=self._model, instructions=instructions,
            untrusted_input=_json(inputs), output_schema=schema,
            max_input_tokens=self._max_input_tokens, max_output_tokens=self._max_output_tokens,
        ))
        return result.value


class GovernedProductOwnerProvider(GovernedRoleAdapter):
    def review_problem(self, problem: ProblemBrief) -> ProblemApproval:
        schema = _object_schema({
            "decision": {"enum": [item.value for item in ProblemDecision]},
            "approved_scope": TEXTS, "constraints": TEXTS, "explicit_non_goals": TEXTS,
            "rationale": {"type": "string"},
        }, ("decision", "approved_scope", "constraints", "explicit_non_goals", "rationale"))
        raw = self._call("review-problem", {"problem": problem}, schema,
                         "Decide product desirability and scope only. Do not claim repository facts.")
        return ProblemApproval(problem.problem_id, problem.version, problem.fingerprint, self.provider_id,
                               ProblemDecision(raw["decision"]), tuple(raw["approved_scope"]),
                               tuple(raw["constraints"]), tuple(raw["explicit_non_goals"]), str(raw["rationale"]))

    def review_solution(self, problem: ProblemBrief, approval: ProblemApproval, solution: SolutionProposal) -> SolutionApproval:
        schema = _object_schema({"decision": {"enum": [item.value for item in SolutionDecision]}, "rationale": {"type": "string"}}, ("decision", "rationale"))
        raw = self._call("review-solution", {"problem": problem, "problem_approval": approval, "solution": solution}, schema,
                         "Check exact problem alignment, approved scope, constraints, and non-goals. Do not verify repository facts.")
        return SolutionApproval(solution.solution_id, solution.version, solution.fingerprint,
                                approval.fingerprint, self.provider_id, SolutionDecision(raw["decision"]), str(raw["rationale"]))


class GovernedOrchestratorProvider(GovernedRoleAdapter):
    _FIELDS = ("scope_delta", "existing_components_reused", "new_components", "domain_changes",
               "state_machine_changes", "persistence_changes", "migration_impact", "concurrency_semantics",
               "authority_changes", "acceptance_invariants", "alternatives_considered", "deferred_items", "affected_work_units")

    def design(self, problem: ProblemBrief, approval: ProblemApproval) -> SolutionProposal:
        props = {"solution_id": TEXT, "version": {"type": "integer", "minimum": 1},
                 "proposed_design": TEXT, "why_this_is_minimal": TEXT,
                 "scope_conformance": {"enum": [item.value for item in ScopeConformance]}}
        props.update({name: TEXTS for name in self._FIELDS})
        raw = self._call("design", {"problem": problem, "problem_approval": approval},
                         _object_schema(props, tuple(props)),
                         "Design only within the exact approval. Declare any scope expansion explicitly.")
        kwargs = {name: tuple(raw[name]) for name in self._FIELDS}
        return SolutionProposal(str(raw["solution_id"]), int(raw["version"]), problem.problem_id,
                                approval.fingerprint, str(raw["proposed_design"]), str(raw["why_this_is_minimal"]),
                                ScopeConformance(raw["scope_conformance"]), approval.approved_scope,
                                approval.explicit_non_goals, **kwargs)

    def expand_problem(self, problem: ProblemBrief, approval: ProblemApproval, solution: SolutionProposal) -> ProblemBrief:
        schema = _object_schema({"title": TEXT, "observed_problem": TEXT, "impact": TEXT,
                                 "evidence_refs": TEXTS, "affected_concepts": TEXTS, "constraints": TEXTS,
                                 "non_goals": TEXTS, "proposed_scope": TEXTS},
                                ("title", "observed_problem", "impact", "evidence_refs", "affected_concepts", "constraints", "non_goals", "proposed_scope"))
        raw = self._call("expand-problem", {"problem": problem, "approval": approval, "solution": solution}, schema,
                         "Create the next ProblemBrief version; preserve identity and make scope delta explicit.")
        return ProblemBrief(problem.problem_id, problem.version + 1, str(raw["title"]), str(raw["observed_problem"]),
                            str(raw["impact"]), tuple(raw["evidence_refs"]), tuple(raw["affected_concepts"]),
                            tuple(raw["constraints"]), tuple(raw["non_goals"]), tuple(raw["proposed_scope"]))


class GovernedChangeExecutor(Protocol):
    """Narrow adapter around an already-authorized implementation/patch runtime."""
    def execute(self, problem: ProblemBrief, solution: SolutionProposal, approval: SolutionApproval) -> None: ...


class GovernedImplementationLifecycleExecutor:
    """Generate and apply one proposal in an exact-base isolated worktree."""

    def __init__(self, runtime_builder: Any, *, repository_root: Path, base_sha: str,
                 organization_id: str, project_id: str | None = None,
                 plan_fingerprint: str | None = None) -> None:
        self._builder = runtime_builder
        self._manager = GitWorktreeManager(repository_root)
        self._base = base_sha
        self._organization_id = organization_id
        self._project_id = project_id
        self._plan_fingerprint = plan_fingerprint
        self.receipt: ArtifactSubmission | None = None

    def execute(self, problem: ProblemBrief, solution: SolutionProposal, approval: SolutionApproval) -> None:
        self.receipt = None
        paths = tuple(sorted(set(solution.new_components + solution.existing_components_reused)))
        if not paths:
            raise RuntimeError("approved solution declares no implementation paths")
        session = self._manager.create_detached_worktree(self._base)
        expected: dict[str, str] = {}

        def materialize(record: Any) -> ArtifactSubmission:
            if record.proposal_id != expected.get("proposal_id"):
                raise RuntimeError("patch record proposal does not match the approved generated proposal")
            commit = self._manager.stage_and_commit(
                session, f"Governed implementation {solution.solution_id}",
                author_name="DOR Governed Coder", author_email="governed-coder@localhost",
                authored_at="2000-01-01T00:00:00+00:00",
            )
            changed = self._manager.changed_files(session, self._base, commit)
            if changed != tuple(expected.get("changed_files", "").split("\n")):
                raise RuntimeError("materialized Git diff does not match the approved generated proposal")
            return ArtifactSubmission(commit, self._base, changed)

        try:
            proposal_runtime, patch_runtime = self._builder(session.worktree_path, materialize)
            if not isinstance(proposal_runtime, ImplementationAgentRuntime):
                raise TypeError("runtime_builder must return an ImplementationAgentRuntime")
            if not isinstance(patch_runtime, GovernedPatchExecutionRuntime):
                raise TypeError("runtime_builder must return a GovernedPatchExecutionRuntime")
            if patch_runtime.proposal_runtime is not proposal_runtime:
                raise RuntimeError("proposal and patch runtimes must share one ImplementationAgentRuntime")
            if patch_runtime.workspace_root != session.worktree_path:
                raise RuntimeError("patch runtime is not bound to the exact-base isolated worktree")
            resource = proposal_runtime.allowed_resources[0]
            fingerprints = {
                "problem": problem.fingerprint,
                "problem_approval": solution.problem_approval_fingerprint,
                "solution": solution.fingerprint,
                "solution_approval": approval.fingerprint,
            }
            context = ContextItem(
                "governance-v0", "approved-contract-fingerprints", fingerprints,
                provenance="GovernanceCoordinator",
            )
            instruction = json.dumps(
                {"approved_design": solution.proposed_design, "allowed_paths": paths,
                 "contract_fingerprints": fingerprints},
                sort_keys=True, separators=(",", ":"), ensure_ascii=False,
            )
            proposed = proposal_runtime.run(
                organization_id=self._organization_id, resource=resource,
                instruction=instruction, allowed_paths=paths, context_items=(context,),
                budget=ChangeBudget(max_files=len(paths), max_changed_lines=1000),
                idempotency_key=f"governance-proposal:{approval.fingerprint}",
                project_id=self._project_id, plan_request_fingerprint=self._plan_fingerprint,
            )
            request = proposed.request
            if (request.organization_id != self._organization_id or request.resource != resource
                    or request.allowed_paths != paths or request.instruction != instruction):
                raise RuntimeError("generated proposal request is not bound to the approved governance input")
            if tuple(item.canonical() for item in request.context_packet.items) != (context.canonical(),):
                raise RuntimeError("generated proposal context is not bound to the approved governance input")
            if proposed.proposal.request_fingerprint != request.request_fingerprint:
                raise RuntimeError("generated proposal identity is not bound to its implementation request")
            expected.update({
                "proposal_id": proposed.proposal.proposal_id,
                "changed_files": "\n".join(proposed.proposal.touched_paths),
            })
            applied = patch_runtime.run(proposal_id=proposed.proposal.proposal_id,
                                        idempotency_key=f"governance-apply:{proposed.proposal.proposal_id}",
                                        organization_id=self._organization_id)
            if (applied.request.request_fingerprint != applied.record.request_fingerprint
                    or applied.request.proposal.request_fingerprint != request.request_fingerprint
                    or applied.record.proposal_id != proposed.proposal.proposal_id):
                raise RuntimeError("patch result is not bound to the approved generated proposal")
            try:
                receipt = patch_runtime.get_materialization_receipt(applied.request.request_fingerprint)
            except PatchExecutionRequestNotFoundError as exc:
                raise RuntimeError(
                    "governed patch execution returned no materialization receipt"
                ) from exc
            if not isinstance(receipt, ArtifactSubmission):
                raise TypeError("governed patch execution returned an invalid materialization receipt")
            self.receipt = receipt
        finally:
            self._manager.cleanup_worktree(session)


class GovernedCoderProvider:
    """Execute through an injected governed runtime, then observe Git state."""
    def __init__(self, provider_id: str, executor: GovernedChangeExecutor, repository_root: str | Path, base_sha: str) -> None:
        if not provider_id.strip():
            raise ValueError("provider_id is required")
        self.provider_id, self._executor, self._root, self._base = provider_id, executor, Path(repository_root), base_sha

    def implement(self, problem: ProblemBrief, solution: SolutionProposal, approval: SolutionApproval) -> ArtifactSubmission:
        self._executor.execute(problem, solution, approval)
        receipt = getattr(self._executor, "receipt", None)
        if not isinstance(receipt, ArtifactSubmission) or receipt.base_version != self._base:
            raise RuntimeError("governed coder execution returned no exact-base materialization receipt")
        return receipt


class GovernedAuditorProvider(GovernedRoleAdapter):
    def verify(self, problem: ProblemBrief, solution: SolutionProposal, submission: ArtifactSubmission, core_evidence: EvidenceReport) -> EvidenceReport:
        schema = _object_schema({"decision": {"enum": [item.value for item in AuditDecision]}, "facts_verified": TEXTS,
                                 "mismatches": TEXTS, "proof_construction_verified": BOOL, "solution_conformance_verified": BOOL},
                                ("decision", "facts_verified", "mismatches", "proof_construction_verified", "solution_conformance_verified"))
        raw = self._call("audit", {"problem": problem, "solution": solution, "submission": submission, "core_evidence": core_evidence}, schema,
                         "Verify proof construction and exact solution conformance. Veto on uncertainty or mismatch.")
        return EvidenceReport(AuditDecision(raw["decision"]), tuple(raw["facts_verified"]), tuple(raw["mismatches"]),
                              bool(raw["proof_construction_verified"]), bool(raw["solution_conformance_verified"]))


class GovernedReviewerProvider(GovernedRoleAdapter):
    def review(self, problem: ProblemBrief, solution: SolutionProposal, submission: ArtifactSubmission, evidence: EvidenceReport) -> IndependentReview:
        schema = _object_schema({"decision": {"enum": [item.value for item in ReviewDecision]}, "findings": TEXTS}, ("decision", "findings"))
        raw = self._call("independent-review", {"problem": problem, "solution": solution, "submission": submission, "verified_evidence": evidence}, schema,
                         "Independently review only the approved contract, exact artifact, and verified evidence. Do not rewrite scope.")
        return IndependentReview(submission.artifact_version, solution.fingerprint, self.provider_id,
                                 ReviewDecision(raw["decision"]), tuple(raw["findings"]))


__all__ = [
    "GovernedAuditorProvider",
    "GovernedCoderProvider",
    "GovernedImplementationLifecycleExecutor",
    "GovernedOrchestratorProvider",
    "GovernedProductOwnerProvider",
    "GovernedReviewerProvider",
    "GovernedRoleAdapter",
]
