"""Governed application orchestration for one observed runtime failure.

This module is deliberately provider neutral.  It joins the existing Redmine,
Work Queue, governance, verification, and release boundaries without owning any
of their authority or lifecycle decisions.  Every returned object is checked
against the deterministic lineage before the next side effect is requested.
"""

from __future__ import annotations

import argparse
import importlib
import json
import os
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, replace
from hashlib import sha256
from typing import Any, Protocol

from domain.capability import Capability
from domain.work_queue import ImmutableVersionRef, WorkUnit, WorkUnitState
from domain.work_queue_readiness import is_ready, is_worker_eligible
from infrastructure.persistence.database import apply_tenant_context
from infrastructure.persistence.work_queue_repository import WorkUnitRepository
from infrastructure.runtime.work_queue_review import WorkQueueReviewService
from infrastructure.runtime.work_queue_scope import (
    ProjectScopedWorkQueueClaimService,
    ProjectScopedWorkQueueLeaseService,
)
from phase4.authority.grants import (
    VerifiedAuthorityGrant,
    sign_configured_provenance,
    verify_configured_provenance,
)
from phase4.contracts import KnowledgeRecord
from phase4.development_governance.contracts import (
    ProblemBrief,
    ReviewDecision,
)
from phase4.development_governance.coordinator import (
    GovernanceCoordinator,
    GovernanceRunResult,
)
from phase6.execution.audit_harness import AuditHarness
from services.github_pr_contracts import PatchInfo, PRMetadata, PRStatus
from services.redmine_contracts import RedmineErrorKind
from services.redmine_error_ticketing import FailureSignature, RedmineErrorTickerService
from services.ship_gate import ShipGate
from services.side_effects import SideEffectCoordinator


class RuntimeFailureRemediationError(RuntimeError):
    """The remediation pipeline could not prove a required invariant."""


def _text(value: object, name: str) -> str:
    if not isinstance(value, str) or not value or value != value.strip():
        raise RuntimeFailureRemediationError(f"{name} must be canonical non-empty text")
    return value


def _sha(value: object) -> str:
    encoded = json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    )
    return sha256(encoded.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class RuntimeFailure:
    organization_id: str
    project_id: str
    plan_fingerprint: str
    repository: str
    base_sha: str
    module: str
    error: str
    context: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for name in ("organization_id", "project_id", "repository", "module", "error"):
            _text(getattr(self, name), name)
        hashes = (("plan_fingerprint", 64), ("base_sha", 40))
        for name, length in hashes:
            value = _text(getattr(self, name), name)
            if len(value) != length or any(c not in "0123456789abcdef" for c in value):
                raise RuntimeFailureRemediationError(
                    f"{name} must be a lowercase immutable hash"
                )

    @property
    def signature(self) -> FailureSignature:
        return FailureSignature.from_verification(
            module=self.module, error=self.error, kind=RedmineErrorKind.EXECUTION
        )

    @property
    def lineage_id(self) -> str:
        return _sha(
            {
                "organization_id": self.organization_id,
                "project_id": self.project_id,
                "plan_fingerprint": self.plan_fingerprint,
                "repository": self.repository,
                "base_sha": self.base_sha,
                "failure_fingerprint": self.signature.fingerprint,
            }
        )


@dataclass(frozen=True)
class IssueBinding:
    issue_id: str
    failure_fingerprint: str


@dataclass(frozen=True)
class Reproduction:
    reproduced: bool
    evidence_ref: str


@dataclass(frozen=True)
class RemediationArtifact:
    version: ImmutableVersionRef
    base_sha: str
    failure_fingerprint: str
    reproduction_ref: str
    patch: str


@dataclass(frozen=True)
class Verification:
    passed: bool
    artifact_version: ImmutableVersionRef
    evidence_ref: str


@dataclass(frozen=True)
class DraftPullRequest:
    pull_request_id: str
    draft: bool
    lineage_id: str
    artifact_version: ImmutableVersionRef


@dataclass(frozen=True)
class RuntimeFailureRemediationResult:
    lineage_id: str
    issue: IssueBinding
    work_unit: WorkUnit
    artifact: RemediationArtifact
    verification: Verification
    draft_pr: DraftPullRequest
    coder_id: str
    reviewer_id: str


class IssuePort(Protocol):
    def ensure_issue(
        self, failure: RuntimeFailure, signature: FailureSignature
    ) -> IssueBinding: ...


class WorkQueuePort(Protocol):
    def get(self, organization_id: str, work_unit_id: str) -> WorkUnit | None: ...

    def ensure_work_unit(
        self, failure: RuntimeFailure, issue: IssueBinding, work_unit: WorkUnit
    ) -> WorkUnit: ...

    def dependencies(
        self, organization_id: str, work_unit: WorkUnit
    ) -> Mapping[str, WorkUnit]: ...

    def scope_is_current(self, organization_id: str, work_unit: WorkUnit) -> bool: ...

    def claim(
        self,
        organization_id: str,
        work_unit_id: str,
        worker_id: str,
        capability: Capability,
    ) -> WorkUnit | None: ...

    def submit(
        self, organization_id: str, work_unit: WorkUnit, artifact: RemediationArtifact
    ) -> WorkUnit | None: ...

    def approve(
        self,
        organization_id: str,
        work_unit: WorkUnit,
        reviewer_id: str,
        artifact_version: ImmutableVersionRef,
    ) -> WorkUnit | None: ...


class RemediationPort(Protocol):
    @property
    def provider_id(self) -> str: ...

    def reproduce(
        self, failure: RuntimeFailure, work_unit: WorkUnit
    ) -> Reproduction: ...

    def remediate(
        self, failure: RuntimeFailure, work_unit: WorkUnit, reproduction: Reproduction
    ) -> tuple[RemediationArtifact, GovernanceRunResult]: ...


class VerificationPort(Protocol):
    def verify(
        self, failure: RuntimeFailure, artifact: RemediationArtifact
    ) -> Verification: ...


class ReleaseAuthorityPort(Protocol):
    def grant_draft(
        self,
        failure: RuntimeFailure,
        artifact: RemediationArtifact,
        verification: Verification,
    ) -> VerifiedAuthorityGrant: ...


class DraftPRPort(Protocol):
    def ensure_draft(
        self,
        failure: RuntimeFailure,
        lineage_id: str,
        artifact: RemediationArtifact,
        grant: VerifiedAuthorityGrant,
    ) -> DraftPullRequest: ...


class RedmineIssueAdapter:
    """Adapt the canonical deduplicating Redmine ticker."""

    def __init__(self, ticker: RedmineErrorTickerService) -> None:
        self._ticker = ticker

    def ensure_issue(
        self, failure: RuntimeFailure, signature: FailureSignature
    ) -> IssueBinding:
        result = self._ticker.report_verification_failure(
            module=failure.module,
            error=failure.error,
            context=dict(failure.context),
            kind=RedmineErrorKind.EXECUTION,
        )
        if not result.ok or result.issue is None:
            raise RuntimeFailureRemediationError(
                f"Redmine issue unavailable: {result.error or 'unknown'}"
            )
        return IssueBinding(str(result.issue.id), signature.fingerprint)


class RepositoryWorkQueueAdapter:
    """Thin adapter over the existing tenant/project-scoped Work Queue services."""

    def __init__(self, session_factory, *, scope_validator) -> None:
        self._sessions = session_factory
        self._scope_validator = scope_validator

    def ensure_work_unit(
        self, failure: RuntimeFailure, issue: IssueBinding, work_unit: WorkUnit
    ) -> WorkUnit:
        with self._sessions() as session:
            apply_tenant_context(session, failure.organization_id)
            repository = WorkUnitRepository(session)
            existing = repository.get(failure.organization_id, work_unit.id)
            if existing is not None:
                return existing
            repository.add(failure.organization_id, work_unit)
            session.commit()
            return work_unit

    def get(self, organization_id: str, work_unit_id: str) -> WorkUnit | None:
        return self._get(organization_id, work_unit_id)

    def dependencies(
        self, organization_id: str, work_unit: WorkUnit
    ) -> Mapping[str, WorkUnit]:
        with self._sessions() as session:
            apply_tenant_context(session, organization_id)
            repository = WorkUnitRepository(session)
            return {
                dependency_id: dependency
                for dependency_id in work_unit.depends_on
                if (dependency := repository.get(organization_id, dependency_id))
                is not None
            }

    def scope_is_current(self, organization_id: str, work_unit: WorkUnit) -> bool:
        project_id, plan = self._scope(work_unit)
        try:
            return bool(self._scope_validator(organization_id, project_id, plan))
        except Exception:  # noqa: BLE001 - provider failures must fail closed
            return False

    def claim(
        self,
        organization_id: str,
        work_unit_id: str,
        worker_id: str,
        capability: Capability,
    ) -> WorkUnit | None:
        current = self._get(organization_id, work_unit_id)
        if current is None:
            return None
        project_id, plan = self._scope(current)
        claimed = ProjectScopedWorkQueueClaimService(
            self._sessions,
            organization_id=organization_id,
            project_id=project_id,
            plan_request_fingerprint=plan,
            scope_validator=self._scope_validator,
        ).claim_ready(work_unit_id, worker_id, (capability,))
        return claimed

    def submit(
        self, organization_id: str, work_unit: WorkUnit, artifact: RemediationArtifact
    ) -> WorkUnit | None:
        if work_unit.lease is None:
            return None
        project_id, plan = self._scope(work_unit)
        return ProjectScopedWorkQueueLeaseService(
            self._sessions,
            organization_id=organization_id,
            project_id=project_id,
            plan_request_fingerprint=plan,
            scope_validator=self._scope_validator,
        ).submit_for_review(
            work_unit.id,
            worker_id=work_unit.claimed_by or "",
            lease_id=work_unit.lease.lease_id,
            delivered_artifact_version=artifact.version,
        )

    def approve(
        self,
        organization_id: str,
        work_unit: WorkUnit,
        reviewer_id: str,
        artifact_version: ImmutableVersionRef,
    ) -> WorkUnit | None:
        return WorkQueueReviewService(
            self._sessions, organization_id=organization_id
        ).approve(
            work_unit.id,
            reviewer_id=reviewer_id,
            artifact_version=artifact_version,
        )

    def _get(self, organization_id: str, work_unit_id: str) -> WorkUnit | None:
        with self._sessions() as session:
            apply_tenant_context(session, organization_id)
            return WorkUnitRepository(session).get(organization_id, work_unit_id)

    @staticmethod
    def _scope(work_unit: WorkUnit) -> tuple[str, str]:
        projects = [
            x.removeprefix("project_scope:project:")
            for x in work_unit.acceptance_refs
            if x.startswith("project_scope:project:")
        ]
        plans = [
            x.removeprefix("project_scope:plan:")
            for x in work_unit.acceptance_refs
            if x.startswith("project_scope:plan:")
        ]
        if len(projects) != 1 or len(plans) != 1:
            raise RuntimeFailureRemediationError(
                "WorkUnit has no canonical project scope"
            )
        return projects[0], plans[0]


class GovernanceCoordinatorRemediationAdapter:
    """Run remediation exclusively through the canonical coordinator/coder runtime."""

    def __init__(
        self,
        coordinator: GovernanceCoordinator,
        problem_factory,
        reproduction_runner,
        patch_loader,
    ) -> None:
        self._coordinator = coordinator
        self._problem_factory = problem_factory
        self._reproduction_runner = reproduction_runner
        self._patch_loader = patch_loader

    @property
    def provider_id(self) -> str:
        return self._coordinator.coder.provider_id

    def reproduce(self, failure: RuntimeFailure, work_unit: WorkUnit) -> Reproduction:
        problem = self._problem_factory(failure, work_unit)
        if not isinstance(problem, ProblemBrief):
            raise RuntimeFailureRemediationError(
                "problem_factory returned no ProblemBrief"
            )
        reproduction = self._reproduction_runner(failure, work_unit, problem)
        if not isinstance(reproduction, Reproduction):
            raise RuntimeFailureRemediationError(
                "reproduction_runner returned no Reproduction evidence"
            )
        return reproduction

    def remediate(
        self,
        failure: RuntimeFailure,
        work_unit: WorkUnit,
        reproduction: Reproduction,
    ) -> tuple[RemediationArtifact, GovernanceRunResult]:
        problem = self._problem_factory(failure, work_unit)
        if not reproduction.reproduced or not reproduction.evidence_ref.strip():
            raise RuntimeFailureRemediationError(
                "reproduction evidence is not successful"
            )
        governed = self._coordinator.run_semantic(problem)
        submission = governed.submission
        patch = self._patch_loader(
            failure.repository, submission.base_version, submission.artifact_version
        )
        return (
            RemediationArtifact(
                version=ImmutableVersionRef("git_commit", submission.artifact_version),
                base_sha=submission.base_version,
                failure_fingerprint=failure.signature.fingerprint,
                reproduction_ref=reproduction.evidence_ref,
                patch=patch,
            ),
            governed,
        )


class VerifiedAuthorityReleaseAdapter:
    """Adapt the existing authority resolver; never manufacture authority."""

    def __init__(self, resolver) -> None:
        self._resolver = resolver

    def grant_draft(
        self,
        failure: RuntimeFailure,
        artifact: RemediationArtifact,
        verification: Verification,
    ) -> VerifiedAuthorityGrant:
        grant = self._resolver(failure, artifact, verification)
        if not isinstance(grant, VerifiedAuthorityGrant):
            raise RuntimeFailureRemediationError(
                "release authority returned no VerifiedAuthorityGrant"
            )
        return grant


class ShipGateDraftPRAdapter:
    """Publish draft-only through existing ShipGate with replay fencing."""

    def __init__(
        self,
        gate: ShipGate,
        *,
        record: KnowledgeRecord,
        test_results: Mapping[str, Any],
        audit_harness: AuditHarness,
        metadata_factory,
        side_effects: SideEffectCoordinator,
    ) -> None:
        self._gate = gate
        self._record = record
        self._tests = dict(test_results)
        self._audit = audit_harness
        self._metadata_factory = metadata_factory
        self._effects = side_effects

    def ensure_draft(
        self,
        failure: RuntimeFailure,
        lineage_id: str,
        artifact: RemediationArtifact,
        grant: VerifiedAuthorityGrant,
    ) -> DraftPullRequest:
        patch = PatchInfo(
            patch_content=artifact.patch,
            patch_id=artifact.version.value,
            author="governed-remediation",
            files_changed=[],
        )
        metadata = self._metadata_factory(failure, artifact)
        if not isinstance(metadata, PRMetadata):
            raise RuntimeFailureRemediationError(
                "metadata_factory returned no PRMetadata"
            )
        metadata = replace(metadata, draft=True)

        def publish() -> Mapping[str, Any]:
            result = self._gate.ship(
                patch=patch,
                pr_metadata=metadata,
                record=self._record,
                grant=grant,
                test_results=self._tests,
                audit_harness=self._audit,
                push_remote=True,
            )
            if result.status is not PRStatus.CREATED:
                raise RuntimeFailureRemediationError("ShipGate did not create a PR")
            return {"id": str(result.pr_number), "url": result.pr_url or ""}

        receipt, _ = self._effects.execute(
            organization_id=failure.organization_id,
            action="runtime-remediation.draft-pr",
            idempotency_key=lineage_id,
            request_data={
                "repository": failure.repository,
                "base_sha": failure.base_sha,
                "artifact": artifact.version.value,
                "grant_id": grant.grant_id,
                "draft": True,
            },
            operation=publish,
        )
        return DraftPullRequest(
            pull_request_id=str(receipt["id"]),
            draft=True,
            lineage_id=lineage_id,
            artifact_version=artifact.version,
        )


@dataclass
class RuntimeFailureRemediation:
    issues: IssuePort
    work_queue: WorkQueuePort
    remediation: RemediationPort
    verification: VerificationPort
    release_authority: ReleaseAuthorityPort
    draft_prs: DraftPRPort
    required_capability: Capability
    side_effects: SideEffectCoordinator

    def run(self, failure: RuntimeFailure) -> RuntimeFailureRemediationResult:
        """Replay completed lineage or execute it under a persistent fence."""
        payload, _ = self.side_effects.execute(
            organization_id=failure.organization_id,
            action="runtime-remediation.pipeline",
            idempotency_key=failure.lineage_id,
            request_data=self._pipeline_request(failure),
            operation=lambda: self._encode(failure, self._run_once(failure)),
        )
        return self._decode(failure, payload)

    def _run_once(self, failure: RuntimeFailure) -> RuntimeFailureRemediationResult:
        """Run the existing governed boundaries in order, failing closed."""
        coder_id = _text(self.remediation.provider_id, "remediation.provider_id")
        signature = failure.signature
        work_unit_id = f"runtime-remediation-{failure.lineage_id[:24]}"
        persistent = self.work_queue.get(failure.organization_id, work_unit_id)
        if persistent is not None:
            if persistent.state is not WorkUnitState.APPROVED:
                raise RuntimeFailureRemediationError(
                    "existing remediation WorkUnit is not safely resumable"
                )
            issue, artifact, coder_id, reviewer_id = self._approved_checkpoint(
                failure, persistent
            )
            return self._verify_and_publish(
                failure, issue, persistent, artifact, coder_id, reviewer_id
            )

        issue = self.issues.ensure_issue(failure, signature)
        if issue.failure_fingerprint != signature.fingerprint:
            raise RuntimeFailureRemediationError(
                "issue is not bound to the failure fingerprint"
            )

        expected = self._expected_work_unit(failure, issue)
        pending = self.work_queue.ensure_work_unit(failure, issue, expected)
        self._require_work_unit(pending, expected, WorkUnitState.PENDING)
        dependencies = self.work_queue.dependencies(failure.organization_id, pending)
        if not is_ready(pending, dependencies) or not is_worker_eligible(
            pending, (self.required_capability,)
        ):
            raise RuntimeFailureRemediationError(
                "work unit is not ready for the required capability"
            )

        claimed = self.work_queue.claim(
            failure.organization_id, pending.id, coder_id, self.required_capability
        )
        self._require_work_unit(claimed, expected, WorkUnitState.CLAIMED)
        if claimed.claimed_by != coder_id or claimed.lease is None:
            raise RuntimeFailureRemediationError(
                "work unit claim lacks coder ownership and lease"
            )

        reproduction = self.remediation.reproduce(failure, claimed)
        if not reproduction.reproduced or not reproduction.evidence_ref.strip():
            raise RuntimeFailureRemediationError("runtime failure was not reproduced")
        artifact, governance = self.remediation.remediate(
            failure, claimed, reproduction
        )
        reviewer_id = _text(governance.review.reviewer_id, "governance reviewer_id")
        if (
            governance.review.decision is not ReviewDecision.APPROVED
            or governance.submission.artifact_version != artifact.version.value
            or governance.submission.base_version != failure.base_sha
            or governance.audit.decision.value != "VERIFIED"
            or coder_id == reviewer_id
        ):
            raise RuntimeFailureRemediationError(
                "GovernanceCoordinator did not independently approve the exact artifact"
            )
        self._require_artifact(failure, reproduction, artifact)

        submitted = self.work_queue.submit(failure.organization_id, claimed, artifact)
        self._require_work_unit(submitted, expected, WorkUnitState.AWAITING_REVIEW)
        if submitted.delivered_artifact_version != artifact.version:
            raise RuntimeFailureRemediationError(
                "submitted WorkUnit is not bound to the artifact"
            )
        approved = self.work_queue.approve(
            failure.organization_id, submitted, reviewer_id, artifact.version
        )
        self._require_work_unit(approved, expected, WorkUnitState.APPROVED)
        if approved.previous_worker == reviewer_id:
            raise RuntimeFailureRemediationError(
                "reviewer cannot be the remediation worker"
            )

        self._store_approved_checkpoint(
            failure, issue, approved, artifact, coder_id, reviewer_id
        )
        return self._verify_and_publish(
            failure, issue, approved, artifact, coder_id, reviewer_id
        )

    def _verify_and_publish(
        self,
        failure: RuntimeFailure,
        issue: IssueBinding,
        approved: WorkUnit,
        artifact: RemediationArtifact,
        coder_id: str,
        reviewer_id: str,
    ) -> RuntimeFailureRemediationResult:
        """Resume only the post-approval verification/release/publication tail."""

        verification = self.verification.verify(failure, artifact)
        if (
            not verification.passed
            or verification.artifact_version != artifact.version
            or not verification.evidence_ref.strip()
        ):
            raise RuntimeFailureRemediationError(
                "independent verification did not approve the exact artifact"
            )
        grant = self.release_authority.grant_draft(failure, artifact, verification)
        self._require_grant(failure, artifact, verification, grant)
        draft = self.draft_prs.ensure_draft(
            failure, failure.lineage_id, artifact, grant
        )
        if (
            not draft.draft
            or draft.lineage_id != failure.lineage_id
            or draft.artifact_version != artifact.version
        ):
            raise RuntimeFailureRemediationError(
                "publisher did not return the exact governed Draft PR"
            )
        return RuntimeFailureRemediationResult(
            failure.lineage_id,
            issue,
            approved,
            artifact,
            verification,
            draft,
            coder_id,
            reviewer_id,
        )

    def _store_approved_checkpoint(
        self,
        failure: RuntimeFailure,
        issue: IssueBinding,
        approved: WorkUnit,
        artifact: RemediationArtifact,
        coder_id: str,
        reviewer_id: str,
    ) -> None:
        payload, replayed = self.side_effects.execute(
            organization_id=failure.organization_id,
            action="runtime-remediation.approved-artifact",
            idempotency_key=failure.lineage_id,
            request_data=self._pipeline_request(failure),
            operation=lambda: self._encode_approved(
                failure, issue, artifact, coder_id, reviewer_id
            ),
        )
        self._validate_receipt(payload, self._approved_receipt_fields())
        checkpoint_issue, checkpoint_artifact, _, _ = self._decode_approved(
            failure, approved, payload
        )
        if replayed and (checkpoint_issue != issue or checkpoint_artifact != artifact):
            raise RuntimeFailureRemediationError(
                "approved artifact checkpoint conflicts with current result"
            )

    def _approved_checkpoint(
        self, failure: RuntimeFailure, approved: WorkUnit
    ) -> tuple[IssueBinding, RemediationArtifact, str, str]:
        payload, replayed = self.side_effects.execute(
            organization_id=failure.organization_id,
            action="runtime-remediation.approved-artifact",
            idempotency_key=failure.lineage_id,
            request_data=self._pipeline_request(failure),
            operation=lambda: (_ for _ in ()).throw(
                RuntimeFailureRemediationError(
                    "APPROVED WorkUnit has no durable artifact checkpoint"
                )
            ),
        )
        if not replayed:
            raise RuntimeFailureRemediationError(
                "APPROVED WorkUnit checkpoint was not replayed"
            )
        self._validate_receipt(payload, self._approved_receipt_fields())
        return self._decode_approved(failure, approved, payload)

    @staticmethod
    def _pipeline_request(failure: RuntimeFailure) -> Mapping[str, Any]:
        return {
            "project_id": failure.project_id,
            "plan_fingerprint": failure.plan_fingerprint,
            "repository": failure.repository,
            "base_sha": failure.base_sha,
            "failure_fingerprint": failure.signature.fingerprint,
        }

    def _receipt_context(
        self, failure: RuntimeFailure, coder_id: str, reviewer_id: str
    ) -> Mapping[str, Any]:
        return {
            "organization_id": failure.organization_id,
            "project_id": failure.project_id,
            "plan_fingerprint": failure.plan_fingerprint,
            "repository": failure.repository,
            "lineage_id": failure.lineage_id,
            "required_capability_id": self.required_capability.id,
            "coder_id": coder_id,
            "reviewer_id": reviewer_id,
        }

    def _expected_work_unit(
        self, failure: RuntimeFailure, issue: IssueBinding
    ) -> WorkUnit:
        return WorkUnit(
            id=f"runtime-remediation-{failure.lineage_id[:24]}",
            title=f"Remediate runtime failure {failure.signature.fingerprint}",
            required_capability=self.required_capability,
            base_version=ImmutableVersionRef("git_commit", failure.base_sha),
            allowed_resources=(f"repository:{failure.repository}",),
            acceptance_refs=(
                f"redmine_issue:{issue.issue_id}",
                f"failure_fingerprint:{failure.signature.fingerprint}",
                f"project_scope:project:{failure.project_id}",
                f"project_scope:plan:{failure.plan_fingerprint}",
            ),
        )

    def _encode_approved(
        self,
        failure: RuntimeFailure,
        issue: IssueBinding,
        artifact: RemediationArtifact,
        coder_id: str,
        reviewer_id: str,
    ) -> Mapping[str, Any]:
        payload = {
            **self._receipt_context(failure, coder_id, reviewer_id),
            "issue_id": issue.issue_id,
            "failure_fingerprint": issue.failure_fingerprint,
            "artifact_kind": artifact.version.kind,
            "artifact_version": artifact.version.value,
            "artifact_base": artifact.base_sha,
            "reproduction_ref": artifact.reproduction_ref,
            "patch": artifact.patch,
        }
        return RuntimeFailureRemediation._seal_receipt(payload)

    @staticmethod
    def _approved_receipt_fields() -> frozenset[str]:
        return frozenset(
            {
                "issue_id",
                "failure_fingerprint",
                "artifact_kind",
                "artifact_version",
                "artifact_base",
                "reproduction_ref",
                "patch",
                "organization_id",
                "project_id",
                "plan_fingerprint",
                "repository",
                "lineage_id",
                "required_capability_id",
                "coder_id",
                "reviewer_id",
                "receipt_fingerprint",
            }
        )

    def _encode(
        self, failure: RuntimeFailure, result: RuntimeFailureRemediationResult
    ) -> Mapping[str, Any]:
        payload = {
            **self._receipt_context(failure, result.coder_id, result.reviewer_id),
            "issue_id": result.issue.issue_id,
            "failure_fingerprint": result.issue.failure_fingerprint,
            "artifact_kind": result.artifact.version.kind,
            "artifact_version": result.artifact.version.value,
            "artifact_base": result.artifact.base_sha,
            "reproduction_ref": result.artifact.reproduction_ref,
            "patch": result.artifact.patch,
            "verification_passed": result.verification.passed,
            "verification_ref": result.verification.evidence_ref,
            "pr_id": result.draft_pr.pull_request_id,
            "pr_draft": result.draft_pr.draft,
            "pr_lineage_id": result.draft_pr.lineage_id,
            "pr_artifact_kind": result.draft_pr.artifact_version.kind,
            "pr_artifact_version": result.draft_pr.artifact_version.value,
        }
        return RuntimeFailureRemediation._seal_receipt(payload)

    def _decode(
        self, failure: RuntimeFailure, payload: Mapping[str, Any]
    ) -> RuntimeFailureRemediationResult:
        self._validate_receipt(
            payload,
            self._approved_receipt_fields()
            | {
                "verification_passed",
                "verification_ref",
                "pr_id",
                "pr_draft",
                "pr_lineage_id",
                "pr_artifact_kind",
                "pr_artifact_version",
            },
        )
        work_unit_id = f"runtime-remediation-{failure.lineage_id[:24]}"
        work_unit = self.work_queue.get(failure.organization_id, work_unit_id)
        if work_unit is None or work_unit.state is not WorkUnitState.APPROVED:
            raise RuntimeFailureRemediationError(
                "completed receipt has no APPROVED WorkUnit"
            )
        issue, artifact, coder_id, reviewer_id = self._decode_approved(
            failure, work_unit, payload
        )
        if payload.get("verification_passed") is not True:
            raise RuntimeFailureRemediationError(
                "replay receipt verification decision changed"
            )
        verification = Verification(
            True,
            artifact.version,
            _text(payload.get("verification_ref"), "verification_ref"),
        )
        pr_version = ImmutableVersionRef(
            _text(payload.get("pr_artifact_kind"), "pr_artifact_kind"),
            _text(payload.get("pr_artifact_version"), "pr_artifact_version"),
        )
        if (
            payload.get("pr_draft") is not True
            or payload.get("pr_lineage_id") != failure.lineage_id
            or pr_version != artifact.version
        ):
            raise RuntimeFailureRemediationError("replay receipt PR lineage changed")
        draft = DraftPullRequest(
            _text(payload.get("pr_id"), "pr_id"),
            True,
            failure.lineage_id,
            artifact.version,
        )
        return RuntimeFailureRemediationResult(
            failure.lineage_id,
            issue,
            work_unit,
            artifact,
            verification,
            draft,
            coder_id,
            reviewer_id,
        )

    @staticmethod
    def _seal_receipt(payload: Mapping[str, Any]) -> Mapping[str, Any]:
        sealed = dict(payload)
        try:
            sealed["receipt_fingerprint"] = sign_configured_provenance(
                "runtime-remediation-receipt", sealed
            )
        except RuntimeError as exc:
            raise RuntimeFailureRemediationError(
                "receipt signing provenance is unavailable"
            ) from exc
        return sealed

    @staticmethod
    def _validate_receipt(
        payload: Mapping[str, Any], expected_fields: frozenset[str] | set[str]
    ) -> None:
        if not isinstance(payload, Mapping) or set(payload) != set(expected_fields):
            raise RuntimeFailureRemediationError("receipt fields changed")
        fingerprint = payload.get("receipt_fingerprint")
        unsealed = {
            key: value for key, value in payload.items() if key != "receipt_fingerprint"
        }
        if not verify_configured_provenance(
            "runtime-remediation-receipt", unsealed, fingerprint
        ):
            raise RuntimeFailureRemediationError("receipt provenance changed")

    def _decode_approved(
        self,
        failure: RuntimeFailure,
        work_unit: WorkUnit,
        payload: Mapping[str, Any],
    ) -> tuple[IssueBinding, RemediationArtifact, str, str]:
        try:
            version = ImmutableVersionRef(
                _text(payload.get("artifact_kind"), "artifact_kind"),
                _text(payload.get("artifact_version"), "artifact_version"),
            )
            issue = IssueBinding(
                _text(payload.get("issue_id"), "issue_id"),
                _text(payload.get("failure_fingerprint"), "failure_fingerprint"),
            )
            artifact = RemediationArtifact(
                version,
                _text(payload.get("artifact_base"), "artifact_base"),
                issue.failure_fingerprint,
                _text(payload.get("reproduction_ref"), "reproduction_ref"),
                _text(payload.get("patch"), "patch"),
            )
            coder_id = _text(payload.get("coder_id"), "coder_id")
            reviewer_id = _text(payload.get("reviewer_id"), "reviewer_id")
        except (KeyError, TypeError, ValueError) as exc:
            raise RuntimeFailureRemediationError(
                "approved artifact receipt is malformed"
            ) from exc
        expected = self._expected_work_unit(failure, issue)
        expected_context = self._receipt_context(failure, coder_id, reviewer_id)
        if (
            any(payload.get(key) != value for key, value in expected_context.items())
            or coder_id == reviewer_id
            or work_unit.id != expected.id
            or work_unit.title != expected.title
            or work_unit.required_capability != expected.required_capability
            or work_unit.base_version != expected.base_version
            or work_unit.allowed_resources != expected.allowed_resources
            or work_unit.acceptance_refs != expected.acceptance_refs
            or work_unit.state is not WorkUnitState.APPROVED
            or work_unit.delivered_artifact_version != version
            or work_unit.previous_worker != coder_id
            or work_unit.previous_worker == reviewer_id
            or not self.work_queue.scope_is_current(failure.organization_id, work_unit)
            or issue.failure_fingerprint != failure.signature.fingerprint
            or artifact.base_sha != failure.base_sha
            or artifact.failure_fingerprint != failure.signature.fingerprint
            or artifact.version.kind != "git_commit"
            or not artifact.version.value.strip()
            or not artifact.reproduction_ref.strip()
            or not artifact.patch.strip()
        ):
            raise RuntimeFailureRemediationError(
                "approved artifact receipt changed governed lineage"
            )
        return issue, artifact, coder_id, reviewer_id

    @staticmethod
    def _require_work_unit(
        actual: WorkUnit | None, expected: WorkUnit, state: WorkUnitState
    ) -> None:
        if (
            actual is None
            or actual.id != expected.id
            or actual.required_capability.id != expected.required_capability.id
            or actual.base_version != expected.base_version
            or actual.allowed_resources != expected.allowed_resources
            or actual.acceptance_refs != expected.acceptance_refs
            or actual.state is not state
        ):
            raise RuntimeFailureRemediationError(
                f"WorkUnit does not match governed {state.name} lineage"
            )

    @staticmethod
    def _require_artifact(
        failure: RuntimeFailure,
        reproduction: Reproduction,
        artifact: RemediationArtifact,
    ) -> None:
        if (
            artifact.base_sha != failure.base_sha
            or artifact.failure_fingerprint != failure.signature.fingerprint
            or artifact.reproduction_ref != reproduction.evidence_ref
            or not artifact.patch.strip()
        ):
            raise RuntimeFailureRemediationError(
                "remediation artifact has invalid lineage"
            )

    @staticmethod
    def _require_grant(
        failure: RuntimeFailure,
        artifact: RemediationArtifact,
        verification: Verification,
        grant: VerifiedAuthorityGrant,
    ) -> None:
        if (
            not grant.verified
            or grant.organization_id != failure.organization_id
            or grant.action != "release.publish"
            or grant.resource != f"repository:{failure.repository}"
            or dict(grant.parameters).get("patch_id") != artifact.version.value
            or dict(grant.parameters).get("base_sha") != failure.base_sha
            or dict(grant.parameters).get("verification_ref")
            != verification.evidence_ref
            or not grant.grant_id.strip()
        ):
            raise RuntimeFailureRemediationError(
                "release grant is not bound to verified artifact lineage"
            )


def _load_runtime_bindings(spec: str) -> Mapping[str, Any]:
    """Load dependency wiring only; the returned objects retain their authorities."""
    module_name, separator, attribute = spec.partition(":")
    if not separator or not module_name or not attribute:
        raise RuntimeFailureRemediationError(
            "DOR_RUNTIME_FAILURE_BINDINGS must be module:callable"
        )
    factory = getattr(importlib.import_module(module_name), attribute, None)
    if not callable(factory):
        raise RuntimeFailureRemediationError(
            "runtime failure bindings factory is not callable"
        )
    bindings = factory()
    if not isinstance(bindings, Mapping):
        raise RuntimeFailureRemediationError(
            "runtime failure bindings factory returned no mapping"
        )
    return bindings


def _failure_from_json(raw: Any) -> RuntimeFailure:
    if not isinstance(raw, dict):
        raise RuntimeFailureRemediationError("failure input must be a JSON object")
    required = {
        "organization_id",
        "project_id",
        "plan_fingerprint",
        "repository",
        "base_sha",
        "module",
        "error",
        "context",
    }
    if set(raw) != required or not isinstance(raw.get("context"), dict):
        raise RuntimeFailureRemediationError(
            "failure input does not match the RuntimeFailure contract"
        )
    return RuntimeFailure(**raw)


def main(argv: Sequence[str] | None = None) -> int:
    """Execute the canonical governed runtime-failure remediation entrypoint."""
    parser = argparse.ArgumentParser(
        description="Run governed remediation for one runtime failure"
    )
    parser.add_argument("--failure", required=True)
    args = parser.parse_args(argv)
    try:
        binding_spec = os.getenv("DOR_RUNTIME_FAILURE_BINDINGS", "").strip()
        if not binding_spec:
            raise RuntimeFailureRemediationError(
                "DOR_RUNTIME_FAILURE_BINDINGS is required"
            )
        with open(args.failure, encoding="utf-8") as stream:
            failure = _failure_from_json(json.load(stream))
        from api.dependencies import build_runtime_failure_remediation

        runtime = build_runtime_failure_remediation(
            **dict(_load_runtime_bindings(binding_spec))
        )
        result = runtime.run(failure)
        print(
            json.dumps(
                {
                    "status": "DRAFT_PR_CREATED",
                    "lineage_id": result.lineage_id,
                    "issue_id": result.issue.issue_id,
                    "artifact_version": result.artifact.version.value,
                    "draft_pr_id": result.draft_pr.pull_request_id,
                },
                sort_keys=True,
                separators=(",", ":"),
            )
        )
        return 0
    except Exception as exc:  # noqa: BLE001 - process boundary must fail closed
        print(
            json.dumps(
                {"status": "FAILED_CLOSED", "error_type": type(exc).__name__},
                sort_keys=True,
                separators=(",", ":"),
            ),
            file=sys.stderr,
        )
        return 2


__all__ = [
    "DraftPRPort",
    "DraftPullRequest",
    "GovernanceCoordinatorRemediationAdapter",
    "IssueBinding",
    "IssuePort",
    "RedmineIssueAdapter",
    "ReleaseAuthorityPort",
    "RemediationArtifact",
    "RemediationPort",
    "RepositoryWorkQueueAdapter",
    "Reproduction",
    "RuntimeFailure",
    "RuntimeFailureRemediation",
    "RuntimeFailureRemediationError",
    "RuntimeFailureRemediationResult",
    "ShipGateDraftPRAdapter",
    "Verification",
    "VerificationPort",
    "VerifiedAuthorityReleaseAdapter",
    "WorkQueuePort",
]


if __name__ == "__main__":
    raise SystemExit(main())
