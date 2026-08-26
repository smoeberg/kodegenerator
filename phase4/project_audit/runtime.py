"""Operational AI-1 through AI-5 application flow for project audits."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from phase4.agent_registry import AgentRegistry, AgentRole, AgentVersion, Capability
from phase4.authority import AuthorityDecision, AuthorityEngine, AuthorityPolicy, AuthorityRule, Decision
from phase4.authority.grants import VerifiedAuthorityGrant
from phase4.context_packet import ContextItem, ContextPacketEngine, ContextRequest
from phase4.execution import ExecutionEngine, ExecutionReplayLedger, ExecutionResult, ExecutionStatus
from phase4.outcome.engine import OutcomeEngine
from phase4.outcome.models import OutcomeRecord, OutcomeStatus

from .adapter import ProjectAuditExecutionAdapter, ProjectAuditProvider
from .collector import ProjectEvidenceCollector
from .models import PROJECT_AUDIT_ACTION, MaturityLevel, ProjectAuditReport, ProjectAuditRequest
from .repository import GitRepositoryManifestBuilder

DEFAULT_AUDIT_OBJECTIVES = (
    "challenge unsupported project-wide claims",
    "identify cross-component integration and operational drift",
    "separate contract completeness from production readiness",
    "recommend the next development priority from repository evidence",
)


class ProjectAuditRuntimeError(RuntimeError):
    """The governed audit flow did not produce a successful AI-5 outcome."""


@dataclass(frozen=True)
class ProjectAuditRun:
    """Validated report plus its exact governance and outcome provenance."""

    agent_identity: str
    authority: AuthorityDecision
    execution: ExecutionResult
    outcome: OutcomeRecord
    report: ProjectAuditReport


class ProjectAuditRuntime:
    """Collect, authorize, execute, and record one read-only project audit."""

    def __init__(self, root: Path, *, max_files: int = 5_000, max_bytes: int = 16 * 1024 * 1024, ledger: ExecutionReplayLedger | None = None) -> None:
        self._ledger = ledger
        self._manifest_builder = GitRepositoryManifestBuilder(root)
        self._collector = ProjectEvidenceCollector(
            self._manifest_builder.root,
            max_files=max_files,
            max_bytes=max_bytes,
        )

    @property
    def root(self) -> Path:
        return self._manifest_builder.root

    def run(
        self,
        *,
        repository: str,
        provider: ProjectAuditProvider,
        revision: str = "HEAD",
        objectives: tuple[str, ...] = DEFAULT_AUDIT_OBJECTIVES,
        target_maturity: MaturityLevel = MaturityLevel.PRODUCTION_READY,
        organization_id: str = "system-audit",
    ) -> ProjectAuditRun:
        if any(character in repository for character in "*?["):
            raise ValueError("repository authority resource must not contain glob characters")
        manifest = self._manifest_builder.build(repository=repository, revision=revision)
        evidence_bundle = self._collector.collect(manifest)

        provider_id = getattr(provider, "provider_id", None)
        if not isinstance(provider_id, str) or not provider_id.strip():
            raise ProjectAuditRuntimeError("project-audit provider must declare a non-empty provider_id")

        registry = AgentRegistry()
        version = AgentVersion(1, 1, 0)
        agent = registry.register(
            agent_type="project-audit-agent",
            version=version,
            role=AgentRole.AUDITOR,
            capabilities=(
                Capability.create(
                    PROJECT_AUDIT_ACTION,
                    version,
                    parameters={"provider": provider_id, "specialization": "project_integrity"},
                ),
            ),
            trust_anchor=manifest.manifest_id,
            actor="project-audit-runtime",
        )
        agent_identity = str(agent.identity)

        context = ContextPacketEngine().build(
            ContextRequest(
                agent_identity=agent_identity,
                purpose=PROJECT_AUDIT_ACTION,
                requested_keys=("audit-boundary", "revision", "roadmap"),
            ),
            (
                ContextItem(
                    source="architecture",
                    key="audit-boundary",
                    value="Advisory read-only audit; P3-20 remains the authoritative PASS/FAIL gate.",
                    provenance="phase4/project_audit/ARCHITECTURE.md",
                ),
                ContextItem(
                    source="repository-manifest",
                    key="revision",
                    value={"commit_sha": manifest.commit_sha, "manifest_id": manifest.manifest_id},
                    provenance=f"git:{manifest.commit_sha}",
                ),
                ContextItem(
                    source="roadmap",
                    key="roadmap",
                    value="Choose the next slice from whole-project evidence, not package-local test success.",
                    provenance="roadmap:phase4b-project-integrity",
                ),
            ),
            actor="project-audit-runtime",
        )
        request = ProjectAuditRequest(
            agent_identity=agent_identity,
            agent_role=agent.role.value,
            resource=repository,
            context_packet=context,
            evidence_bundle=evidence_bundle,
            objectives=objectives,
            organization_id=organization_id,
            target_maturity=target_maturity,
        )

        # AI-3 evaluates this exact request. AI-4 receives an execution request
        # carrying the same canonical identity and parameters.
        authority_request = request.authority_request()
        execution_request = request.execution_request(
            idempotency_key=f"project-audit:{request.request_fingerprint}",
        )
        if execution_request.request_id != authority_request.request_id:
            raise ProjectAuditRuntimeError("AI-3 authority request identity differs from AI-4 execution request")
        if execution_request.parameters != authority_request.parameters:
            raise ProjectAuditRuntimeError("AI-3 authority parameters differ from AI-4 execution parameters")

        authority = AuthorityEngine(
            AuthorityPolicy(
                policy_id="policy.project-audit.runtime",
                version="1",
                rules=(
                    AuthorityRule(
                        rule_id="allow-exact-read-only-project-audit",
                        action=PROJECT_AUDIT_ACTION,
                        resource_pattern=repository,
                        effect=Decision.ALLOW,
                        agent_identity=agent_identity,
                        agent_role=agent.role.value,
                        required_context=tuple(sorted(request.authority_context().items())),
                    ),
                ),
            )
        ).evaluate(authority_request)
        if not authority.allowed:
            raise ProjectAuditRuntimeError("AI-3 denied the exact project-audit request")

        grant = VerifiedAuthorityGrant.from_decision(authority)
        if not grant.binds(execution_request):
            raise ProjectAuditRuntimeError("AI-3 grant is not bound to the exact AI-4 execution request")

        adapter = ProjectAuditExecutionAdapter(
            adapter_id=f"adapter.project-audit.runtime:{provider_id}",
            provider=provider,
            requests=(request,),
        )
        execution = ExecutionEngine((adapter,), ledger=self._ledger).execute(execution_request, grant)
        outcome = OutcomeEngine().process(execution)
        if execution.status is not ExecutionStatus.SUCCEEDED:
            raise ProjectAuditRuntimeError(execution.error or "AI-4 project audit did not succeed")
        if outcome.status is not OutcomeStatus.SUCCEEDED:
            raise ProjectAuditRuntimeError("AI-5 project-audit outcome did not succeed")

        output = dict(execution.output)
        report_id = output.get("report_id")
        if report_id is None:
            raise ProjectAuditRuntimeError("AI-4 output contains no report identity")
        report = adapter.get_report(report_id)
        return ProjectAuditRun(
            agent_identity=agent_identity,
            authority=authority,
            execution=execution,
            outcome=outcome,
            report=report,
        )
