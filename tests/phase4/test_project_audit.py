"""Contract tests for Phase 4B-2 Project Audit Agent."""

from __future__ import annotations

import hashlib
from dataclasses import FrozenInstanceError, replace

import pytest

from phase4.authority import AuthorityEngine, AuthorityPolicy, AuthorityRule, Decision
from phase4.context_packet import ContextItem, ContextPacketEngine, ContextRequest
from phase4.execution import ExecutionEngine, ExecutionStatus
from phase4.project_audit import (
    PROJECT_AUDIT_ACTION,
    AuditFindingCandidate,
    AuditRecommendation,
    DuplicateProjectAuditRequestError,
    EvidenceAssertion,
    EvidenceIntegrityError,
    EvidenceKind,
    EvidenceLimitError,
    EvidencePredicate,
    FindingClassification,
    FindingSeverity,
    InvalidProjectAuditReportError,
    ManifestEntry,
    MaturityAssessment,
    MaturityLevel,
    MaturityStatus,
    ProjectAuditCandidate,
    ProjectAuditContractError,
    ProjectAuditExecutionAdapter,
    ProjectAuditReport,
    ProjectAuditReportNotFoundError,
    ProjectAuditRequest,
    ProjectEvidenceCollector,
    RepositoryManifest,
)
from phase4.project_audit.testing import DeterministicFakeProjectAuditProvider

REPOSITORY = "repository:smoeberg/kodegenerator"
COMMIT_SHA = "a" * 40


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def make_bundle(tmp_path, *, files=None, max_files=100, max_bytes=100_000):
    contents = files or {
        ".env.example": b"DOR_JWT_SECRET_KEY=change-me\n",
        ".github/workflows/ci.yml": b"run: python -m compileall api domain\n",
        "alembic/versions/001.py": b"revision = '001'\n",
        "phase4/implementation_agent/models.py": (
            b"class ImplementationRequest:\n    pass\n"
        ),
        "README.md": b"# Example project\n",
    }
    for path, content in contents.items():
        target = tmp_path / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
    manifest = RepositoryManifest(
        repository=REPOSITORY,
        commit_sha=COMMIT_SHA,
        entries=tuple(
            ManifestEntry(path=path, sha256=_sha256(content))
            for path, content in reversed(tuple(contents.items()))
        ),
    )
    return ProjectEvidenceCollector(
        tmp_path,
        max_files=max_files,
        max_bytes=max_bytes,
    ).collect(manifest)


def make_request(tmp_path, *, agent_identity="agent.project-auditor"):
    bundle = make_bundle(tmp_path)
    context = ContextPacketEngine().build(
        ContextRequest(
            agent_identity=agent_identity,
            purpose=PROJECT_AUDIT_ACTION,
            requested_keys=("roadmap", "risk-register"),
        ),
        (
            ContextItem(
                source="roadmap",
                key="roadmap",
                value="Assess system coherence before selecting another slice.",
                provenance="roadmap:phase4b-2",
            ),
            ContextItem(
                source="risk-register",
                key="risk-register",
                value="Package-level green tests may hide integration drift.",
                provenance="risk:RISK-GLOBAL-COHERENCE",
            ),
        ),
    )
    return ProjectAuditRequest(
        agent_identity=agent_identity,
        agent_role="auditor",
        resource=REPOSITORY,
        context_packet=context,
        evidence_bundle=bundle,
        objectives=(
            "distinguish observed facts from inference",
            "assess cross-project maturity",
        ),
    )


def make_candidate(
    *,
    recommendation=AuditRecommendation.REPLAN,
    migration_predicate=EvidencePredicate.PATH_EXISTS,
):
    findings = (
        AuditFindingCandidate(
            key="migrations-observed",
            title="Canonical migration evidence exists",
            classification=FindingClassification.FACT,
            severity=FindingSeverity.INFO,
            summary="At least one migration is present in the bound manifest.",
            rationale="The exact manifested path exists.",
            evidence=(
                EvidenceAssertion(
                    "alembic/versions/001.py",
                    migration_predicate,
                ),
            ),
        ),
        AuditFindingCandidate(
            key="ci-phase4-coverage-gap",
            title="CI compile coverage excludes Phase 4",
            classification=FindingClassification.FACT,
            severity=FindingSeverity.HIGH,
            summary="The compile command does not name the Phase 4 package.",
            rationale="The exact CI text lacks the required package token.",
            evidence=(
                EvidenceAssertion(
                    ".github/workflows/ci.yml",
                    EvidencePredicate.TEXT_ABSENT,
                    "phase4",
                ),
            ),
            consequences=("Import regressions can escape the compile step.",),
        ),
    )
    maturity = (
        MaturityAssessment(
            MaturityLevel.CONTRACT_COMPLETE,
            MaturityStatus.ACHIEVED,
            "The implementation contract is present.",
            ("migrations-observed",),
        ),
        MaturityAssessment(
            MaturityLevel.INTEGRATED,
            MaturityStatus.GAPPED,
            "Cross-package compile coverage is incomplete.",
            ("ci-phase4-coverage-gap",),
        ),
        MaturityAssessment(
            MaturityLevel.OPERATIONAL,
            MaturityStatus.UNKNOWN,
            "Runtime evidence is insufficient.",
            ("ci-phase4-coverage-gap",),
        ),
        MaturityAssessment(
            MaturityLevel.E2E_VERIFIED,
            MaturityStatus.GAPPED,
            "No end-to-end evidence is in the sample.",
            ("ci-phase4-coverage-gap",),
        ),
        MaturityAssessment(
            MaturityLevel.PRODUCTION_READY,
            MaturityStatus.GAPPED,
            "Higher maturity levels remain gapped.",
            ("ci-phase4-coverage-gap",),
        ),
    )
    return ProjectAuditCandidate(
        findings=findings,
        maturity=maturity,
        recommendation=recommendation,
    )


def allow_decision(request):
    authority_request = request.authority_request()
    policy = AuthorityPolicy(
        policy_id="policy.project-audit",
        version="1",
        rules=(
            AuthorityRule(
                rule_id="allow-exact-project-audit",
                action=PROJECT_AUDIT_ACTION,
                resource_pattern=request.resource,
                effect=Decision.ALLOW,
                agent_identity=request.agent_identity,
                agent_role=request.agent_role,
                required_context=tuple(sorted(request.authority_context().items())),
            ),
        ),
    )
    return AuthorityEngine(policy).evaluate(authority_request)


class TestEvidenceCollection:
    def test_manifest_and_bundle_are_order_independent_and_content_addressed(
        self, tmp_path
    ):
        first = make_bundle(tmp_path / "first")
        second = make_bundle(tmp_path / "second")

        assert first.manifest.manifest_id == second.manifest.manifest_id
        assert first.bundle_id == second.bundle_id
        assert tuple(item.path for item in first.artifacts) == tuple(
            sorted(item.path for item in first.artifacts)
        )
        assert len(first.bundle_id) == 64

    def test_collector_classifies_cross_project_evidence(self, tmp_path):
        bundle = make_bundle(tmp_path)
        kinds = {item.path: item.kind for item in bundle.artifacts}

        assert kinds[".github/workflows/ci.yml"] is EvidenceKind.CI
        assert kinds["alembic/versions/001.py"] is EvidenceKind.MIGRATION
        assert kinds["phase4/implementation_agent/models.py"] is EvidenceKind.SOURCE
        assert kinds["README.md"] is EvidenceKind.ARCHITECTURE
        assert kinds[".env.example"] is EvidenceKind.CONFIGURATION

    @pytest.mark.parametrize(
        "path",
        ("/etc/passwd", "../secret", "src/../secret", "src\\app.py", " src/app.py"),
    )
    def test_manifest_rejects_unsafe_or_noncanonical_paths(self, path):
        with pytest.raises(ProjectAuditContractError):
            ManifestEntry(path, "a" * 64)

    def test_incomplete_or_duplicate_manifest_fails_closed(self):
        entry = ManifestEntry("README.md", "a" * 64)
        with pytest.raises(ProjectAuditContractError, match="complete"):
            RepositoryManifest(REPOSITORY, COMMIT_SHA, (entry,), complete=False)
        with pytest.raises(ProjectAuditContractError, match="unique"):
            RepositoryManifest(REPOSITORY, COMMIT_SHA, (entry, entry))

    def test_hash_drift_and_missing_files_are_rejected(self, tmp_path):
        path = tmp_path / "README.md"
        path.write_text("changed", encoding="utf-8")
        manifest = RepositoryManifest(
            REPOSITORY,
            COMMIT_SHA,
            (ManifestEntry("README.md", _sha256(b"expected")),),
        )
        with pytest.raises(EvidenceIntegrityError, match="mismatch"):
            ProjectEvidenceCollector(tmp_path).collect(manifest)

        path.unlink()
        with pytest.raises(EvidenceIntegrityError, match="missing"):
            ProjectEvidenceCollector(tmp_path).collect(manifest)

    def test_symlink_is_rejected_even_when_target_is_inside_root(self, tmp_path):
        target = tmp_path / "real.txt"
        target.write_text("evidence", encoding="utf-8")
        link = tmp_path / "linked.txt"
        link.symlink_to(target)
        manifest = RepositoryManifest(
            REPOSITORY,
            COMMIT_SHA,
            (ManifestEntry("linked.txt", _sha256(b"evidence")),),
        )
        with pytest.raises(EvidenceIntegrityError, match="symlink"):
            ProjectEvidenceCollector(tmp_path).collect(manifest)

    def test_file_and_byte_limits_never_silently_truncate(self, tmp_path):
        with pytest.raises(EvidenceLimitError, match="file limit"):
            make_bundle(tmp_path / "files", max_files=1)
        with pytest.raises(EvidenceLimitError, match="byte limit"):
            make_bundle(tmp_path / "bytes", max_bytes=5)

    def test_binary_evidence_keeps_identity_without_inventing_text(self, tmp_path):
        bundle = make_bundle(tmp_path, files={"asset.bin": b"\xff\x00"})
        artifact = bundle.artifact("asset.bin")

        assert artifact is not None
        assert artifact.content is None
        assert artifact.byte_count == 2


class TestProjectAuditRequestAndReport:
    def test_request_is_immutable_and_binds_whole_evidence_scope(self, tmp_path):
        request = make_request(tmp_path)
        authority_request = request.authority_request()

        assert len(request.request_fingerprint) == 64
        assert dict(authority_request.context) == request.authority_context()
        assert (
            dict(authority_request.context)["evidence_bundle_id"]
            == request.evidence_bundle.bundle_id
        )
        assert authority_request.action == PROJECT_AUDIT_ACTION
        assert not hasattr(request, "authorize")
        with pytest.raises(FrozenInstanceError):
            request.resource = "repository:other"

    def test_objective_order_does_not_change_request_identity(self, tmp_path):
        request = make_request(tmp_path)
        reversed_request = replace(
            request, objectives=tuple(reversed(request.objectives))
        )

        assert reversed_request.objectives == request.objectives
        assert reversed_request.request_fingerprint == request.request_fingerprint

    def test_context_and_repository_must_match_request(self, tmp_path):
        request = make_request(tmp_path)
        with pytest.raises(ProjectAuditContractError, match="agent identity"):
            replace(request, agent_identity="agent.other")
        with pytest.raises(ProjectAuditContractError, match="resource"):
            replace(request, resource="repository:other")

    def test_valid_report_is_advisory_content_addressed_and_immutable(self, tmp_path):
        request = make_request(tmp_path)
        candidate = make_candidate()
        first = ProjectAuditReport(request, "fake.audit", candidate)
        second = ProjectAuditReport(request, "fake.audit", candidate)

        assert first.report_id == second.report_id
        assert len(first.report_id) == 64
        assert first.authoritative is False
        assert not hasattr(first, "pass_fail")
        assert not hasattr(first, "approve")
        with pytest.raises(FrozenInstanceError):
            first.provider_id = "tampered"

    def test_report_identity_ignores_provider_set_order(self, tmp_path):
        request = make_request(tmp_path)
        candidate = make_candidate()
        reordered = replace(
            candidate,
            findings=tuple(reversed(candidate.findings)),
            maturity=tuple(reversed(candidate.maturity)),
        )

        assert ProjectAuditReport(request, "fake.audit", candidate).report_id == (
            ProjectAuditReport(request, "fake.audit", reordered).report_id
        )

    def test_false_claim_that_migrations_are_missing_is_rejected(self, tmp_path):
        request = make_request(tmp_path)
        candidate = make_candidate(migration_predicate=EvidencePredicate.PATH_ABSENT)

        with pytest.raises(
            InvalidProjectAuditReportError, match="unsupported evidence"
        ):
            ProjectAuditReport(request, "fake.audit", candidate)

    def test_text_claim_on_binary_or_missing_artifact_is_rejected(self, tmp_path):
        request = make_request(tmp_path)
        bad = replace(
            make_candidate().findings[0],
            evidence=(
                EvidenceAssertion(
                    "missing.py",
                    EvidencePredicate.TEXT_CONTAINS,
                    "unsafe claim",
                ),
            ),
        )
        candidate = replace(
            make_candidate(),
            findings=(bad, make_candidate().findings[1]),
        )
        with pytest.raises(InvalidProjectAuditReportError):
            ProjectAuditReport(request, "fake.audit", candidate)

    def test_provider_cannot_understate_high_validated_fact(self, tmp_path):
        request = make_request(tmp_path)
        candidate = make_candidate(
            recommendation=AuditRecommendation.CONTINUE_WITH_GAPS
        )

        with pytest.raises(InvalidProjectAuditReportError, match="minimum is replan"):
            ProjectAuditReport(request, "fake.audit", candidate)

    def test_maturity_must_cover_all_levels_and_reference_real_findings(self, tmp_path):
        with pytest.raises(ProjectAuditContractError, match="every maturity level"):
            replace(make_candidate(), maturity=make_candidate().maturity[:-1])

        request = make_request(tmp_path)
        maturity = list(make_candidate().maturity)
        maturity[0] = replace(maturity[0], finding_keys=("invented",))
        candidate = replace(make_candidate(), maturity=tuple(maturity))
        with pytest.raises(InvalidProjectAuditReportError, match="unknown findings"):
            ProjectAuditReport(request, "fake.audit", candidate)


class TestProjectAuditAdapter:
    def test_authorized_request_produces_only_an_advisory_report(self, tmp_path):
        request = make_request(tmp_path)
        provider = DeterministicFakeProjectAuditProvider(
            {request.request_fingerprint: make_candidate()}
        )
        adapter = ProjectAuditExecutionAdapter(
            adapter_id="adapter.project-audit.fake",
            provider=provider,
            requests=(request,),
        )
        result = ExecutionEngine((adapter,)).execute(
            request.execution_request(idempotency_key="audit-1"),
            allow_decision(request),
        )

        assert result.status is ExecutionStatus.SUCCEEDED
        output = dict(result.output)
        report = adapter.get_report(output["report_id"])
        assert output["authoritative"] == "false"
        assert output["recommendation"] == "replan"
        assert report.request is request
        assert provider.calls == (request.request_fingerprint,)
        assert not hasattr(adapter, "write")
        assert not hasattr(adapter, "run")

    def test_denied_request_never_reaches_provider(self, tmp_path):
        request = make_request(tmp_path)
        provider = DeterministicFakeProjectAuditProvider(
            {request.request_fingerprint: make_candidate()}
        )
        adapter = ProjectAuditExecutionAdapter(
            adapter_id="adapter.project-audit.fake",
            provider=provider,
            requests=(request,),
        )
        denied = replace(allow_decision(request), decision=Decision.DENY)

        result = ExecutionEngine((adapter,)).execute(
            request.execution_request(), denied
        )

        assert result.status is ExecutionStatus.REJECTED
        assert provider.calls == ()

    def test_tampered_or_unregistered_requests_fail_before_provider(self, tmp_path):
        request = make_request(tmp_path)
        provider = DeterministicFakeProjectAuditProvider(
            {request.request_fingerprint: make_candidate()}
        )
        adapter = ProjectAuditExecutionAdapter(
            adapter_id="adapter.project-audit.fake",
            provider=provider,
            requests=(request,),
        )
        tampered = replace(
            request.execution_request(),
            parameters=(
                ("audit_request_fingerprint", request.request_fingerprint),
                ("unapproved", "widened"),
            ),
        )

        result = ExecutionEngine((adapter,)).execute(tampered, allow_decision(request))
        assert result.status is ExecutionStatus.FAILED
        assert "parameters does not match" in result.error
        assert provider.calls == ()

        empty_adapter = ProjectAuditExecutionAdapter(
            adapter_id="adapter.project-audit.empty",
            provider=provider,
        )
        result = ExecutionEngine((empty_adapter,)).execute(
            request.execution_request(), allow_decision(request)
        )
        assert result.status is ExecutionStatus.FAILED
        assert "ProjectAuditRequestNotFoundError" in result.error
        assert provider.calls == ()

    def test_duplicate_registration_and_unknown_report_fail_explicitly(self, tmp_path):
        request = make_request(tmp_path)
        provider = DeterministicFakeProjectAuditProvider(
            {request.request_fingerprint: make_candidate()}
        )
        with pytest.raises(DuplicateProjectAuditRequestError):
            ProjectAuditExecutionAdapter(
                adapter_id="adapter.project-audit.fake",
                provider=provider,
                requests=(request, request),
            )

        adapter = ProjectAuditExecutionAdapter(
            adapter_id="adapter.project-audit.fake",
            provider=provider,
            requests=(request,),
        )
        with pytest.raises(ProjectAuditReportNotFoundError):
            adapter.get_report("missing")

    def test_execution_replay_does_not_call_provider_twice(self, tmp_path):
        request = make_request(tmp_path)
        provider = DeterministicFakeProjectAuditProvider(
            {request.request_fingerprint: make_candidate()}
        )
        adapter = ProjectAuditExecutionAdapter(
            adapter_id="adapter.project-audit.fake",
            provider=provider,
            requests=(request,),
        )
        engine = ExecutionEngine((adapter,))
        execution_request = request.execution_request(idempotency_key="audit-replay")
        authority = allow_decision(request)

        first = engine.execute(execution_request, authority)
        second = engine.execute(execution_request, authority)

        assert first.status is ExecutionStatus.SUCCEEDED
        assert second.status is ExecutionStatus.REPLAYED
        assert provider.calls == (request.request_fingerprint,)
        assert len(adapter.reports()) == 1
