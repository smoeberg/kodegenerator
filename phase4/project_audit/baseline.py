"""Deterministic DOR integrity baseline for credential-free audits.

This provider is intentionally conservative.  It reports only fixed,
machine-checkable repository observations.  It is useful as a reproducible
minimum audit and as counterevidence for a model-backed provider; it is not a
replacement for semantic model reasoning.
"""

from __future__ import annotations

from .models import (
    AuditFindingCandidate,
    AuditRecommendation,
    EvidenceAssertion,
    EvidencePredicate,
    FindingClassification,
    FindingSeverity,
    MaturityAssessment,
    MaturityLevel,
    MaturityStatus,
    ProjectAuditCandidate,
    ProjectAuditRequest,
)


class DORBaselineProjectAuditProvider:
    """Produce the reproducible minimum project-integrity assessment for DOR."""

    provider_id = "baseline.dor-project-integrity.v1"

    def audit_project(self, request: ProjectAuditRequest) -> ProjectAuditCandidate:
        bundle = request.evidence_bundle
        findings: list[AuditFindingCandidate] = []

        first_path = bundle.artifacts[0].path
        findings.append(
            _finding(
                "complete-revision-snapshot",
                "Complete revision snapshot collected",
                FindingClassification.FACT,
                FindingSeverity.INFO,
                "The audit is bound to a complete tracked-file manifest.",
                "The collector observed every entry in the revision manifest.",
                _exists(first_path),
            )
        )

        if _paths_exist(
            request,
            "phase4/project_audit/models.py",
            "phase4/project_audit/adapter.py",
            "tests/phase4/test_project_audit.py",
        ):
            findings.append(
                _finding(
                    "project-audit-contract-present",
                    "Project Audit contract and tests are present",
                    FindingClassification.FACT,
                    FindingSeverity.INFO,
                    "Phase 4B-2 has an evidence contract, adapter, and tests.",
                    "All three exact contract paths exist in the revision.",
                    _exists("phase4/project_audit/models.py"),
                    _exists("phase4/project_audit/adapter.py"),
                    _exists("tests/phase4/test_project_audit.py"),
                )
            )

        migration_path = next(
            (
                item.path
                for item in bundle.artifacts
                if item.path.startswith("alembic/versions/")
                and item.path.endswith(".py")
            ),
            None,
        )
        if migration_path is not None:
            findings.append(
                _finding(
                    "migration-history-present",
                    "Canonical migration history is present",
                    FindingClassification.FACT,
                    FindingSeverity.INFO,
                    "The repository contains versioned Alembic migration evidence.",
                    "At least one exact migration path exists in the manifest.",
                    _exists(migration_path),
                )
            )

        if _paths_exist(request, ".env.example"):
            findings.append(
                _finding(
                    "environment-template-present",
                    "Environment template is present",
                    FindingClassification.FACT,
                    FindingSeverity.INFO,
                    "The repository includes a root environment template.",
                    "The complete manifest contains .env.example.",
                    _exists(".env.example"),
                )
            )

        if _all_hold(
            request,
            _contains("main.py", "Intent("),
            _absent("main.py", "from domain.intent import Intent"),
        ):
            findings.append(
                _finding(
                    "root-entrypoint-unbound-intent",
                    "Root entrypoint references an unbound Intent symbol",
                    FindingClassification.FACT,
                    FindingSeverity.HIGH,
                    "The root script uses Intent without importing or defining it.",
                    "Both the use and the missing explicit import are observed in main.py.",
                    _contains("main.py", "Intent("),
                    _absent("main.py", "from domain.intent import Intent"),
                    consequences=(
                        "Running the root entrypoint fails before a workflow can start.",
                    ),
                )
            )

        if _all_hold(
            request,
            _contains("docker-compose.yml", "JWT_SECRET_KEY="),
            _contains("api/auth.py", 'os.getenv("DOR_JWT_SECRET_KEY")'),
        ):
            findings.append(
                _finding(
                    "deployment-jwt-variable-drift",
                    "Deployment uses the wrong JWT environment variable",
                    FindingClassification.FACT,
                    FindingSeverity.HIGH,
                    "Docker Compose configures JWT_SECRET_KEY while the API requires DOR_JWT_SECRET_KEY.",
                    "The two exact environment-variable names differ in deployment and runtime evidence.",
                    _contains("docker-compose.yml", "JWT_SECRET_KEY="),
                    _contains("api/auth.py", 'os.getenv("DOR_JWT_SECRET_KEY")'),
                    consequences=(
                        "The documented Compose startup cannot satisfy the API fail-closed authentication configuration.",
                    ),
                )
            )

        if _all_hold(
            request,
            _contains(
                "monitoring/tracer.py", "FastAPIInstrumentor.instrument_app(app)"
            ),
            _absent("monitoring/tracer.py", "from api.main import app"),
            _absent("requirements.txt", "opentelemetry-exporter-otlp"),
        ):
            findings.append(
                _finding(
                    "tracing-entrypoint-incomplete",
                    "Tracing module is not import-operational",
                    FindingClassification.FACT,
                    FindingSeverity.HIGH,
                    "The tracer instruments an unbound app and imports an undeclared exporter dependency.",
                    "The source use and both missing bindings are exact repository observations.",
                    _contains(
                        "monitoring/tracer.py",
                        "FastAPIInstrumentor.instrument_app(app)",
                    ),
                    _absent("monitoring/tracer.py", "from api.main import app"),
                    _absent("requirements.txt", "opentelemetry-exporter-otlp"),
                    consequences=(
                        "Tracing cannot be imported as an operational runtime component.",
                    ),
                )
            )

        if _all_hold(
            request,
            _contains("runtime/model_registry.py", "from domain.model import"),
            _path_absent("domain/model.py"),
        ):
            findings.append(
                _finding(
                    "model-registry-import-gap",
                    "Model registry imports a missing domain module",
                    FindingClassification.FACT,
                    FindingSeverity.MEDIUM,
                    "The registry references domain.model, which is absent from the complete manifest.",
                    "The import is present and the exact target path is absent.",
                    _contains("runtime/model_registry.py", "from domain.model import"),
                    _path_absent("domain/model.py"),
                    consequences=(
                        "The advertised central model registry is not currently importable.",
                    ),
                )
            )

        if _all_hold(
            request,
            _contains("dashboard/app.py", 'os.getenv("DOR_ADMIN_PASSWORD",'),
            _contains("dashboard/app.py", "return plain_key"),
            _path_absent("domain/predefined_roles.py"),
        ):
            findings.append(
                _finding(
                    "dashboard-security-and-import-gap",
                    "Dashboard combines fail-open secrets with a missing import",
                    FindingClassification.FACT,
                    FindingSeverity.HIGH,
                    "The dashboard has a default admin password, returns plaintext on encryption failure, and imports a missing module.",
                    "All three conditions are directly observable in the complete revision.",
                    _contains("dashboard/app.py", 'os.getenv("DOR_ADMIN_PASSWORD",'),
                    _contains("dashboard/app.py", "return plain_key"),
                    _path_absent("domain/predefined_roles.py"),
                    consequences=(
                        "The dashboard is neither fail-closed for secrets nor import-operational.",
                    ),
                )
            )

        if _all_hold(
            request,
            _exists(".github/workflows/ci.yml"),
            _absent(".github/workflows/ci.yml", "phase4"),
            _absent(".github/workflows/ci.yml", "dashboard"),
            _absent(".github/workflows/ci.yml", "services"),
        ):
            findings.append(
                _finding(
                    "ci-cross-project-compile-gap",
                    "CI compile gate omits cross-project packages",
                    FindingClassification.FACT,
                    FindingSeverity.MEDIUM,
                    "The explicit compile command omits Phase 4, dashboard, and services packages.",
                    "Each package token is absent from the bound workflow text.",
                    _absent(".github/workflows/ci.yml", "phase4"),
                    _absent(".github/workflows/ci.yml", "dashboard"),
                    _absent(".github/workflows/ci.yml", "services"),
                    consequences=(
                        "Package import drift can escape the dedicated compile gate.",
                    ),
                )
            )

        if _all_hold(
            request,
            _exists("phase4/implementation_agent/models.py"),
            _exists("tests/phase4/test_implementation_agent.py"),
            _absent("api/main.py", "implementation_agent"),
        ):
            findings.append(
                _finding(
                    "implementation-agent-not-runtime-integrated",
                    "Implementation Agent remains contract-only",
                    FindingClassification.INFERENCE,
                    FindingSeverity.MEDIUM,
                    "The package and tests exist without canonical API wiring.",
                    "Contract evidence is present while the canonical API contains no implementation-agent reference.",
                    _exists("phase4/implementation_agent/models.py"),
                    _exists("tests/phase4/test_implementation_agent.py"),
                    _absent("api/main.py", "implementation_agent"),
                )
            )

        if _all_hold(
            request,
            _exists("phase4/project_audit/models.py"),
            _path_absent("phase4/project_audit/cli.py"),
            _path_absent("phase4/project_audit/runtime.py"),
        ):
            findings.append(
                _finding(
                    "project-audit-not-operational",
                    "Project Audit Agent has no runtime command",
                    FindingClassification.FACT,
                    FindingSeverity.MEDIUM,
                    "The contract exists, but the revision has no CLI or runtime module.",
                    "The complete manifest proves both operational entrypoint paths are absent.",
                    _exists("phase4/project_audit/models.py"),
                    _path_absent("phase4/project_audit/cli.py"),
                    _path_absent("phase4/project_audit/runtime.py"),
                )
            )

        keys = {item.key for item in findings}
        anchor = "complete-revision-snapshot"
        contract_complete = "project-audit-contract-present" in keys
        contract_key = "project-audit-contract-present" if contract_complete else anchor
        integration_gaps = _present_keys(
            keys,
            "implementation-agent-not-runtime-integrated",
            "model-registry-import-gap",
        )
        operational_gaps = _present_keys(
            keys,
            "root-entrypoint-unbound-intent",
            "deployment-jwt-variable-drift",
            "tracing-entrypoint-incomplete",
            "model-registry-import-gap",
        )
        e2e_gaps = _present_keys(
            keys,
            "ci-cross-project-compile-gap",
            "project-audit-not-operational",
        )
        production_gaps = _present_keys(
            keys,
            "dashboard-security-and-import-gap",
            "deployment-jwt-variable-drift",
            "tracing-entrypoint-incomplete",
        )

        maturity = (
            MaturityAssessment(
                MaturityLevel.CONTRACT_COMPLETE,
                (
                    MaturityStatus.ACHIEVED
                    if contract_complete
                    else MaturityStatus.UNKNOWN
                ),
                (
                    "The governed Project Audit contract is present and evidence-bound."
                    if contract_complete
                    else "The baseline lacks evidence of the governed Project Audit contract."
                ),
                (contract_key,),
            ),
            MaturityAssessment(
                MaturityLevel.INTEGRATED,
                _gap_or_unknown(integration_gaps),
                (
                    "Specialist contracts are not consistently connected to the canonical runtime."
                    if integration_gaps
                    else "The baseline has insufficient evidence to establish runtime integration."
                ),
                integration_gaps or (anchor,),
            ),
            MaturityAssessment(
                MaturityLevel.OPERATIONAL,
                _gap_or_unknown(operational_gaps),
                (
                    "Tracked runtime, deployment, or observability entrypoints remain incoherent."
                    if operational_gaps
                    else "The baseline has insufficient evidence to establish operational readiness."
                ),
                operational_gaps or (anchor,),
            ),
            MaturityAssessment(
                MaturityLevel.E2E_VERIFIED,
                _gap_or_unknown(e2e_gaps),
                (
                    "The complete system lacks a project-audit runtime proof and full compile coverage."
                    if e2e_gaps
                    else "The baseline has insufficient evidence to establish end-to-end verification."
                ),
                e2e_gaps or (anchor,),
            ),
            MaturityAssessment(
                MaturityLevel.PRODUCTION_READY,
                _gap_or_unknown(production_gaps),
                (
                    "Security, deployment, and operational gaps prevent a production claim."
                    if production_gaps
                    else "The baseline has insufficient evidence for a production-readiness claim."
                ),
                production_gaps or (anchor,),
            ),
        )
        return ProjectAuditCandidate(
            findings=tuple(findings),
            maturity=maturity,
            recommendation=AuditRecommendation.REPLAN,
        )


def _finding(
    key: str,
    title: str,
    classification: FindingClassification,
    severity: FindingSeverity,
    summary: str,
    rationale: str,
    *evidence: EvidenceAssertion,
    consequences: tuple[str, ...] = (),
) -> AuditFindingCandidate:
    return AuditFindingCandidate(
        key=key,
        title=title,
        classification=classification,
        severity=severity,
        summary=summary,
        rationale=rationale,
        evidence=tuple(evidence),
        consequences=consequences,
    )


def _exists(path: str) -> EvidenceAssertion:
    return EvidenceAssertion(path, EvidencePredicate.PATH_EXISTS)


def _path_absent(path: str) -> EvidenceAssertion:
    return EvidenceAssertion(path, EvidencePredicate.PATH_ABSENT)


def _contains(path: str, value: str) -> EvidenceAssertion:
    return EvidenceAssertion(path, EvidencePredicate.TEXT_CONTAINS, value)


def _absent(path: str, value: str) -> EvidenceAssertion:
    return EvidenceAssertion(path, EvidencePredicate.TEXT_ABSENT, value)


def _paths_exist(request: ProjectAuditRequest, *paths: str) -> bool:
    return all(request.evidence_bundle.artifact(path) is not None for path in paths)


def _all_hold(
    request: ProjectAuditRequest,
    *assertions: EvidenceAssertion,
) -> bool:
    bundle = request.evidence_bundle
    for assertion in assertions:
        artifact = bundle.artifact(assertion.path)
        if assertion.predicate is EvidencePredicate.PATH_EXISTS:
            holds = artifact is not None
        elif assertion.predicate is EvidencePredicate.PATH_ABSENT:
            holds = artifact is None
        elif artifact is None or artifact.content is None:
            holds = False
        elif assertion.predicate is EvidencePredicate.TEXT_CONTAINS:
            holds = (assertion.expected or "") in artifact.content
        elif assertion.predicate is EvidencePredicate.TEXT_ABSENT:
            holds = (assertion.expected or "") not in artifact.content
        else:
            holds = artifact.sha256 == assertion.expected
        if not holds:
            return False
    return True


def _present_keys(keys: set[str], *ordered: str) -> tuple[str, ...]:
    return tuple(key for key in ordered if key in keys)


def _gap_or_unknown(gaps: tuple[str, ...]) -> MaturityStatus:
    return MaturityStatus.GAPPED if gaps else MaturityStatus.UNKNOWN
