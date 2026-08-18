"""Reference flow for a whole-project adversarial audit through AI-1 to AI-5."""

from __future__ import annotations

import hashlib

from phase4.agent_registry import AgentRegistry, AgentRole, AgentVersion, Capability
from phase4.authority import AuthorityEngine, AuthorityPolicy, AuthorityRule, Decision
from phase4.authority.grants import VerifiedAuthorityGrant
from phase4.context_packet import ContextItem, ContextPacketEngine, ContextRequest
from phase4.execution import ExecutionEngine, ExecutionStatus
from phase4.outcome.engine import OutcomeEngine
from phase4.outcome.models import OutcomeStatus
from phase4.project_audit import (
    PROJECT_AUDIT_ACTION,
    AuditFindingCandidate,
    AuditRecommendation,
    EvidenceAssertion,
    EvidencePredicate,
    FindingClassification,
    FindingSeverity,
    ManifestEntry,
    MaturityAssessment,
    MaturityLevel,
    MaturityStatus,
    ProjectAuditCandidate,
    ProjectAuditExecutionAdapter,
    ProjectAuditRequest,
    ProjectEvidenceCollector,
    RepositoryManifest,
)
from phase4.project_audit.testing import DeterministicFakeProjectAuditProvider


def test_project_auditor_rejects_false_claims_and_reports_global_drift_ai1_to_ai5(
    tmp_path,
):
    files = {
        ".env.example": "DOR_JWT_SECRET_KEY=change-me\n",
        ".github/workflows/ci.yml": (
            "run: python -m compileall -q api domain runtime\n"
        ),
        "alembic/versions/006_merge_heads.py": "revision = '006_merge_heads'\n",
        "api/main.py": "app = FastAPI()\n",
        "main.py": "asyncio.run(main())\n",
        "phase4/implementation_agent/models.py": "class PatchProposal: pass\n",
        "tests/phase4/test_implementation_agent.py": (
            "def test_patch_contract(): assert True\n"
        ),
    }
    for path, content in files.items():
        target = tmp_path / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")

    repository = "repository:smoeberg/kodegenerator"
    manifest = RepositoryManifest(
        repository=repository,
        commit_sha="b" * 40,
        entries=tuple(
            ManifestEntry(
                path,
                hashlib.sha256(content.encode("utf-8")).hexdigest(),
            )
            for path, content in files.items()
        ),
    )
    bundle = ProjectEvidenceCollector(tmp_path).collect(manifest)

    registry = AgentRegistry()
    agent = registry.register(
        agent_type="project-audit-agent",
        version=AgentVersion(1, 0, 0),
        role=AgentRole.AUDITOR,
        capabilities=(
            Capability.create(
                PROJECT_AUDIT_ACTION,
                AgentVersion(1, 0, 0),
                parameters={"specialization": "project_integrity"},
            ),
        ),
        actor="phase4b-bootstrap",
    )
    context = ContextPacketEngine().build(
        ContextRequest(
            agent_identity=str(agent.identity),
            purpose=PROJECT_AUDIT_ACTION,
            requested_keys=("roadmap", "accepted-debt"),
        ),
        (
            ContextItem(
                source="roadmap",
                key="roadmap",
                value="Select the next slice from whole-project evidence.",
                provenance="roadmap:phase4b-2",
            ),
            ContextItem(
                source="risk-register",
                key="accepted-debt",
                value="Implementation Agent is contract-complete, not integrated.",
                provenance="risk:RISK-INTEGRATION-1",
            ),
        ),
    )
    request = ProjectAuditRequest(
        agent_identity=str(agent.identity),
        agent_role=agent.role.value,
        resource=repository,
        context_packet=context,
        evidence_bundle=bundle,
        objectives=("challenge false findings", "find cross-project drift"),
    )

    findings = (
        AuditFindingCandidate(
            key="migrations-present",
            title="Migration evidence is present",
            classification=FindingClassification.FACT,
            severity=FindingSeverity.INFO,
            summary="The report must not claim migrations are absent.",
            rationale="The canonical migration path exists in the complete manifest.",
            evidence=(
                EvidenceAssertion(
                    "alembic/versions/006_merge_heads.py",
                    EvidencePredicate.PATH_EXISTS,
                ),
            ),
        ),
        AuditFindingCandidate(
            key="environment-template-present",
            title="Environment template is present",
            classification=FindingClassification.FACT,
            severity=FindingSeverity.INFO,
            summary="The report must not claim .env.example is absent.",
            rationale="The exact root path exists in the complete manifest.",
            evidence=(
                EvidenceAssertion(
                    ".env.example",
                    EvidencePredicate.PATH_EXISTS,
                ),
            ),
        ),
        AuditFindingCandidate(
            key="root-entrypoint-drift",
            title="Root entrypoint is not the canonical API",
            classification=FindingClassification.FACT,
            severity=FindingSeverity.HIGH,
            summary="The root script invokes an undefined local main coroutine.",
            rationale="The script calls main but contains no function definition.",
            evidence=(
                EvidenceAssertion(
                    "main.py",
                    EvidencePredicate.TEXT_CONTAINS,
                    "asyncio.run(main())",
                ),
                EvidenceAssertion(
                    "main.py",
                    EvidencePredicate.TEXT_ABSENT,
                    "async def main",
                ),
            ),
            consequences=("A documented or accidental root startup path fails.",),
        ),
        AuditFindingCandidate(
            key="ci-phase4-gap",
            title="CI compile command excludes Phase 4",
            classification=FindingClassification.FACT,
            severity=FindingSeverity.MEDIUM,
            summary="Package imports are tested but not compile-enumerated globally.",
            rationale="The exact workflow text does not name phase4.",
            evidence=(
                EvidenceAssertion(
                    ".github/workflows/ci.yml",
                    EvidencePredicate.TEXT_ABSENT,
                    "phase4",
                ),
            ),
        ),
        AuditFindingCandidate(
            key="implementation-not-integrated",
            title="Implementation Agent remains contract-only",
            classification=FindingClassification.INFERENCE,
            severity=FindingSeverity.MEDIUM,
            summary="Contract and tests exist without canonical API wiring.",
            rationale=(
                "The evidence shows the isolated package and tests, while the canonical "
                "API contains no implementation-agent reference."
            ),
            evidence=(
                EvidenceAssertion(
                    "phase4/implementation_agent/models.py",
                    EvidencePredicate.PATH_EXISTS,
                ),
                EvidenceAssertion(
                    "tests/phase4/test_implementation_agent.py",
                    EvidencePredicate.PATH_EXISTS,
                ),
                EvidenceAssertion(
                    "api/main.py",
                    EvidencePredicate.TEXT_ABSENT,
                    "implementation_agent",
                ),
            ),
        ),
    )
    maturity = (
        MaturityAssessment(
            MaturityLevel.CONTRACT_COMPLETE,
            MaturityStatus.ACHIEVED,
            "The specialist contract and its tests exist.",
            ("implementation-not-integrated",),
        ),
        MaturityAssessment(
            MaturityLevel.INTEGRATED,
            MaturityStatus.GAPPED,
            "The canonical API does not reference the package.",
            ("implementation-not-integrated",),
        ),
        MaturityAssessment(
            MaturityLevel.OPERATIONAL,
            MaturityStatus.GAPPED,
            "The root entrypoint is incoherent.",
            ("root-entrypoint-drift",),
        ),
        MaturityAssessment(
            MaturityLevel.E2E_VERIFIED,
            MaturityStatus.GAPPED,
            "Compile coverage and integration evidence are incomplete.",
            ("ci-phase4-gap", "implementation-not-integrated"),
        ),
        MaturityAssessment(
            MaturityLevel.PRODUCTION_READY,
            MaturityStatus.GAPPED,
            "Operational and E2E prerequisites are not achieved.",
            ("root-entrypoint-drift", "ci-phase4-gap"),
        ),
    )
    candidate = ProjectAuditCandidate(
        findings=findings,
        maturity=maturity,
        recommendation=AuditRecommendation.REPLAN,
    )
    provider = DeterministicFakeProjectAuditProvider(
        {request.request_fingerprint: candidate}
    )
    adapter = ProjectAuditExecutionAdapter(
        adapter_id="adapter.project-audit.reference",
        provider=provider,
        requests=(request,),
    )
    authority = AuthorityEngine(
        AuthorityPolicy(
            policy_id="policy.phase4b.project-audit",
            version="1",
            rules=(
                AuthorityRule(
                    rule_id="allow-bound-project-audit",
                    action=PROJECT_AUDIT_ACTION,
                    resource_pattern=repository,
                    effect=Decision.ALLOW,
                    agent_identity=str(agent.identity),
                    agent_role=AgentRole.AUDITOR.value,
                    required_context=tuple(sorted(request.authority_context().items())),
                ),
            ),
        )
    ).evaluate(request.authority_request())

    execution = ExecutionEngine((adapter,)).execute(
        request.execution_request(idempotency_key="phase4b-2-acceptance"),
        VerifiedAuthorityGrant.from_decision(authority),
    )
    outcome = OutcomeEngine().process(execution)

    assert agent.has_capability(PROJECT_AUDIT_ACTION)
    assert authority.allowed is True
    assert execution.status is ExecutionStatus.SUCCEEDED
    assert outcome.status is OutcomeStatus.SUCCEEDED
    report = adapter.get_report(dict(execution.output)["report_id"])
    assert report.recommendation is AuditRecommendation.REPLAN
    assert report.authoritative is False
    assert {finding.key for finding in report.findings} == {
        "migrations-present",
        "environment-template-present",
        "root-entrypoint-drift",
        "ci-phase4-gap",
        "implementation-not-integrated",
    }
    assert provider.calls == (request.request_fingerprint,)
    assert not hasattr(report, "pass_fail")
    assert not hasattr(report, "authorize")
