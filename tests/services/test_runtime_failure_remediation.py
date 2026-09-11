import base64
import hashlib
import json
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

import services.runtime_failure_remediation as remediation_module
from domain.capability import Capability
from domain.work_queue import ImmutableVersionRef, WorkerLease, WorkUnitState
from infrastructure.persistence.models import Base, TerminalSideEffectModel
from infrastructure.persistence.side_effect_store import SQLAlchemySideEffectStore
from phase4.authority.grants import VerifiedAuthorityGrant
from phase4.development_governance.contracts import AuditDecision, ReviewDecision
from services.runtime_failure_remediation import (
    DraftPullRequest,
    IssueBinding,
    RemediationArtifact,
    Reproduction,
    RuntimeFailure,
    RuntimeFailureRemediation,
    RuntimeFailureRemediationError,
    Verification,
)
from services.side_effects import InMemorySideEffectStore, SideEffectCoordinator

BASE = "b186688707e3c01c8e311f38cc428b10f915ae42"
CAP = Capability(id="python.remediation", name="Python remediation")


@pytest.fixture(autouse=True)
def configured_receipt_provenance(monkeypatch):
    monkeypatch.setenv(
        "DOR_AUTHORITY_SIGNING_KEY",
        base64.urlsafe_b64encode(b"runtime-remediation-test-key-32b").decode(),
    )


def failure():
    return RuntimeFailure(
        "org-1",
        "project-1",
        "a" * 64,
        "owner/repo",
        BASE,
        "api.runtime",
        "ConnectionError",
    )


class Port:
    def __init__(self, calls):
        self.calls, self.current = calls, None

    def ensure_issue(self, item, signature):
        self.calls.append("issue")
        return IssueBinding("42", signature.fingerprint)

    def get(self, organization_id, work_unit_id):
        return (
            self.current if self.current and self.current.id == work_unit_id else None
        )

    def ensure_work_unit(self, item, issue, work_unit):
        self.calls.append("work-unit")
        self.current = work_unit
        return work_unit

    def dependencies(self, organization_id, work_unit):
        self.calls.append("readiness")
        return {}

    def scope_is_current(self, organization_id, work_unit):
        return True

    def claim(self, organization_id, work_unit_id, worker_id, capability):
        self.calls.append("claim")
        now = datetime.now(timezone.utc)
        self.current = replace(
            self.current,
            state=WorkUnitState.CLAIMED,
            claimed_by=worker_id,
            lease=WorkerLease("lease", worker_id, now, now + timedelta(minutes=1)),
        )
        return self.current

    def submit(self, organization_id, work_unit, artifact):
        self.calls.append("submit")
        self.current = replace(
            work_unit,
            state=WorkUnitState.AWAITING_REVIEW,
            claimed_by=None,
            lease=None,
            previous_worker=work_unit.claimed_by,
            delivered_artifact_version=artifact.version,
        )
        return self.current

    def approve(self, organization_id, work_unit, reviewer_id, artifact_version):
        self.calls.append("approve")
        self.current = replace(work_unit, state=WorkUnitState.APPROVED)
        return self.current


class Remediator:
    provider_id = "coder-provider"

    def __init__(self, calls):
        self.calls = calls

    def reproduce(self, item, work_unit):
        self.calls.append("reproduce")
        return Reproduction(True, "reproduction-1")

    def remediate(self, item, work_unit, reproduction):
        self.calls.append("governance-coordinator")
        artifact = RemediationArtifact(
            ImmutableVersionRef("git_commit", "c" * 40),
            item.base_sha,
            item.signature.fingerprint,
            reproduction.evidence_ref,
            "diff --git a/a b/a",
        )
        result = SimpleNamespace(
            submission=SimpleNamespace(
                artifact_version=artifact.version.value, base_version=item.base_sha
            ),
            audit=SimpleNamespace(decision=AuditDecision.VERIFIED),
            review=SimpleNamespace(
                reviewer_id="reviewer-provider", decision=ReviewDecision.APPROVED
            ),
        )
        return artifact, result


class Verifier:
    def __init__(self, calls, passed=True):
        self.calls, self.passed = calls, passed

    def verify(self, item, artifact):
        self.calls.append("verify")
        return Verification(self.passed, artifact.version, "verification-1")


class Authority:
    def __init__(self, calls):
        self.calls = calls

    def grant_draft(self, item, artifact, verification):
        self.calls.append("grant")
        grant = MagicMock(spec=VerifiedAuthorityGrant)
        grant.verified, grant.organization_id = True, item.organization_id
        grant.action, grant.resource = (
            "release.publish",
            f"repository:{item.repository}",
        )
        grant.parameters = (
            ("patch_id", artifact.version.value),
            ("base_sha", item.base_sha),
            ("verification_ref", verification.evidence_ref),
        )
        grant.grant_id = "grant-1"
        return grant


class Drafts:
    def __init__(self, calls):
        self.calls = calls

    def ensure_draft(self, item, lineage_id, artifact, grant):
        self.calls.append("ship-gate")
        return DraftPullRequest("7", True, lineage_id, artifact.version)


def pipeline(passed=True, side_effect_store=None):
    calls = []
    port = Port(calls)
    return RuntimeFailureRemediation(
        port,
        port,
        Remediator(calls),
        Verifier(calls, passed),
        Authority(calls),
        Drafts(calls),
        CAP,
        SideEffectCoordinator(side_effect_store or InMemorySideEffectStore()),
    ), calls


def test_governed_order_and_lineage():
    service, calls = pipeline()
    assert service.run(failure()).draft_pr.draft
    assert calls == [
        "issue",
        "work-unit",
        "readiness",
        "claim",
        "reproduce",
        "governance-coordinator",
        "submit",
        "approve",
        "verify",
        "grant",
        "ship-gate",
    ]
    assert service.run(failure()).draft_pr.pull_request_id == "7"
    assert calls.count("governance-coordinator") == 1


def test_reproduction_required_before_governance():
    service, calls = pipeline()
    service.remediation.reproduce = lambda *_: Reproduction(False, "failed")
    with pytest.raises(RuntimeFailureRemediationError, match="not reproduced"):
        service.run(failure())
    assert "governance-coordinator" not in calls


def test_governance_reviewer_must_differ_from_coder():
    service, calls = pipeline()
    original = service.remediation.remediate

    def same(*args):
        artifact, governed = original(*args)
        governed.review.reviewer_id = "coder-provider"
        return artifact, governed

    service.remediation.remediate = same
    with pytest.raises(RuntimeFailureRemediationError, match="independently approve"):
        service.run(failure())
    assert "submit" not in calls


def test_failed_verification_stops_authority_and_publication():
    service, calls = pipeline(False)
    with pytest.raises(
        RuntimeFailureRemediationError, match="verification did not approve"
    ):
        service.run(failure())
    assert "grant" not in calls and "ship-gate" not in calls


def durable_pipeline(tmp_path, passed=True):
    engine = create_engine(f"sqlite:///{tmp_path / 'remediation.db'}")
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine, expire_on_commit=False)
    service, calls = pipeline(
        passed, SQLAlchemySideEffectStore(sessions, lease_seconds=60)
    )
    return service, calls, sessions


def test_retry_resumes_approved_artifact_without_rerunning_governance(tmp_path):
    service, calls, _ = durable_pipeline(tmp_path, passed=False)
    with pytest.raises(RuntimeFailureRemediationError, match="verification"):
        service.run(failure())
    assert service.work_queue.current.state is WorkUnitState.APPROVED
    completed_before_retry = tuple(calls)

    service.verification.passed = True
    result = service.run(failure())

    assert (
        result.artifact.version == service.work_queue.current.delivered_artifact_version
    )
    assert calls[: len(completed_before_retry)] == list(completed_before_retry)
    assert calls[len(completed_before_retry) :] == ["verify", "grant", "ship-gate"]
    assert calls.count("issue") == 1
    assert calls.count("claim") == 1
    assert calls.count("reproduce") == 1
    assert calls.count("governance-coordinator") == 1


@pytest.mark.parametrize(
    ("field", "tampered"),
    [
        ("issue_id", "99"),
        ("failure_fingerprint", "f" * 64),
        ("artifact_kind", "document_revision"),
        ("artifact_version", "d" * 40),
        ("artifact_base", "e" * 40),
        ("reproduction_ref", "different-reproduction"),
        ("patch", "different-patch"),
        ("verification_passed", False),
        ("verification_ref", "different-verification"),
        ("pr_id", "99"),
        ("pr_draft", False),
        ("pr_lineage_id", "another-lineage"),
        ("pr_artifact_kind", "document_revision"),
        ("pr_artifact_version", "d" * 40),
    ],
)
def test_durable_completed_receipt_tampering_fails_closed(tmp_path, field, tampered):
    service, _, sessions = durable_pipeline(tmp_path)
    service.run(failure())
    with sessions() as session, session.begin():
        row = session.scalar(
            select(TerminalSideEffectModel).where(
                TerminalSideEffectModel.organization_id == "org-1",
                TerminalSideEffectModel.action == "runtime-remediation.pipeline",
                TerminalSideEffectModel.idempotency_key == failure().lineage_id,
            )
        )
        assert row is not None
        receipt = dict(row.result)
        receipt[field] = tampered
        row.result = receipt

    with pytest.raises(RuntimeFailureRemediationError):
        service.run(failure())


def test_durable_approved_checkpoint_tampering_blocks_resume(tmp_path):
    service, calls, sessions = durable_pipeline(tmp_path, passed=False)
    with pytest.raises(RuntimeFailureRemediationError, match="verification"):
        service.run(failure())
    with sessions() as session, session.begin():
        row = session.scalar(
            select(TerminalSideEffectModel).where(
                TerminalSideEffectModel.organization_id == "org-1",
                TerminalSideEffectModel.action
                == "runtime-remediation.approved-artifact",
                TerminalSideEffectModel.idempotency_key == failure().lineage_id,
            )
        )
        assert row is not None
        receipt = dict(row.result)
        receipt["patch"] = "different-nonempty-patch"
        row.result = receipt
    calls_before_retry = tuple(calls)
    service.verification.passed = True

    with pytest.raises(RuntimeFailureRemediationError, match="provenance changed"):
        service.run(failure())
    assert tuple(calls) == calls_before_retry


@pytest.mark.parametrize(
    "mutation",
    [
        lambda wu: replace(
            wu,
            required_capability=Capability(
                id="different.capability", name="Different capability"
            ),
        ),
        lambda wu: replace(wu, allowed_resources=("repository:attacker/repo",)),
        lambda wu: replace(wu, acceptance_refs=wu.acceptance_refs[:-1]),
        lambda wu: replace(wu, previous_worker="different-coder"),
    ],
)
def test_signed_checkpoint_rejects_independently_mutated_work_unit(tmp_path, mutation):
    service, calls, _ = durable_pipeline(tmp_path, passed=False)
    with pytest.raises(RuntimeFailureRemediationError, match="verification"):
        service.run(failure())
    service.work_queue.current = mutation(service.work_queue.current)
    calls_before_retry = tuple(calls)

    with pytest.raises(RuntimeFailureRemediationError, match="governed lineage"):
        service.run(failure())
    assert tuple(calls) == calls_before_retry


@pytest.mark.parametrize(
    "changes",
    [
        {"organization_id": "other-org"},
        {"project_id": "other-project"},
        {"plan_fingerprint": "b" * 64},
        {"repository": "other/repo"},
    ],
)
def test_authentic_checkpoint_cannot_be_transplanted_to_other_lineage(
    tmp_path, changes
):
    service, _, sessions = durable_pipeline(tmp_path, passed=False)
    item = failure()
    with pytest.raises(RuntimeFailureRemediationError, match="verification"):
        service.run(item)
    with sessions() as session:
        row = session.scalar(
            select(TerminalSideEffectModel).where(
                TerminalSideEffectModel.organization_id == item.organization_id,
                TerminalSideEffectModel.action
                == "runtime-remediation.approved-artifact",
                TerminalSideEffectModel.idempotency_key == item.lineage_id,
            )
        )
        authentic_payload = dict(row.result)
    transplanted = replace(item, **changes)

    with pytest.raises(RuntimeFailureRemediationError, match="governed lineage"):
        service._decode_approved(
            transplanted, service.work_queue.current, authentic_payload
        )


def test_approved_resume_rejects_superseded_project_scope(tmp_path):
    service, _, _ = durable_pipeline(tmp_path, passed=False)
    with pytest.raises(RuntimeFailureRemediationError, match="verification"):
        service.run(failure())
    service.work_queue.scope_is_current = lambda *_: False

    with pytest.raises(RuntimeFailureRemediationError, match="governed lineage"):
        service.run(failure())


def test_storage_writer_cannot_reseal_changed_receipt_with_plain_sha(tmp_path):
    service, _, sessions = durable_pipeline(tmp_path)
    service.run(failure())
    with sessions() as session, session.begin():
        row = session.scalar(
            select(TerminalSideEffectModel).where(
                TerminalSideEffectModel.organization_id == "org-1",
                TerminalSideEffectModel.action == "runtime-remediation.pipeline",
                TerminalSideEffectModel.idempotency_key == failure().lineage_id,
            )
        )
        receipt = dict(row.result)
        receipt["patch"] = "writer-controlled-patch"
        unsigned = {k: v for k, v in receipt.items() if k != "receipt_fingerprint"}
        receipt["receipt_fingerprint"] = hashlib.sha256(
            json.dumps(unsigned, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        row.result = receipt

    with pytest.raises(RuntimeFailureRemediationError, match="provenance changed"):
        service.run(failure())


def test_receipt_creation_fails_closed_without_signing_material(monkeypatch):
    service, _ = pipeline()
    monkeypatch.delenv("DOR_AUTHORITY_SIGNING_KEY")
    with pytest.raises(
        RuntimeFailureRemediationError, match="provenance is unavailable"
    ):
        service.run(failure())


def test_existing_nonapproved_work_unit_fails_closed():
    service, _ = pipeline()
    item = failure()
    issue = service.issues.ensure_issue(item, item.signature)
    expected = service.work_queue.ensure_work_unit(
        item,
        issue,
        remediation_module.WorkUnit(
            id=f"runtime-remediation-{item.lineage_id[:24]}",
            title="not safely resumable",
            required_capability=CAP,
        ),
    )
    assert expected.state is WorkUnitState.PENDING
    with pytest.raises(RuntimeFailureRemediationError, match="not safely resumable"):
        service.run(item)


def test_canonical_entrypoint_builds_and_executes_runtime(
    tmp_path, monkeypatch, capsys
):
    item = failure()
    input_path = tmp_path / "failure.json"
    input_path.write_text(
        json.dumps(
            {
                "organization_id": item.organization_id,
                "project_id": item.project_id,
                "plan_fingerprint": item.plan_fingerprint,
                "repository": item.repository,
                "base_sha": item.base_sha,
                "module": item.module,
                "error": item.error,
                "context": dict(item.context),
            }
        ),
        encoding="utf-8",
    )
    service, _ = pipeline()
    builder = MagicMock(return_value=service)
    monkeypatch.setenv("DOR_RUNTIME_FAILURE_BINDINGS", "configured:bindings")
    monkeypatch.setattr(
        remediation_module, "_load_runtime_bindings", lambda _: {"bound": True}
    )
    monkeypatch.setattr("api.dependencies.build_runtime_failure_remediation", builder)

    assert remediation_module.main(["--failure", str(input_path)]) == 0
    assert builder.call_args.kwargs == {"bound": True}
    assert json.loads(capsys.readouterr().out)["status"] == "DRAFT_PR_CREATED"


def test_canonical_entrypoint_fails_closed_without_bindings(
    tmp_path, monkeypatch, capsys
):
    input_path = tmp_path / "unused.json"
    monkeypatch.delenv("DOR_RUNTIME_FAILURE_BINDINGS", raising=False)
    assert remediation_module.main(["--failure", str(input_path)]) == 2
    assert json.loads(capsys.readouterr().err) == {
        "error_type": "RuntimeFailureRemediationError",
        "status": "FAILED_CLOSED",
    }
