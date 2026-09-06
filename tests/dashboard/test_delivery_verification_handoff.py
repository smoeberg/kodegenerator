"""Trust-boundary tests for the post-apply delivery verification handoff."""
from __future__ import annotations

import copy
import hashlib
import json
from datetime import datetime, timezone

import pytest

from dashboard.delivery_verification import (
    DeliveryVerificationGUIError,
    build_delivery_verification_candidate,
)
from dashboard.implementation_proposal import (
    ImplementationScope,
    build_proposal_payload,
    default_implementation_instruction,
)
from dashboard.project_planning import ProjectPlanningInput, generate_project_plan
from phase4.delivery_certificate import DeliveryVerificationStatus
from phase4.onboarding import OnboardingIntent, OnboardingIntentDraft, OnboardingPurpose


def _digest(value: object) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode("utf-8")
    ).hexdigest()


def _intent() -> OnboardingIntent:
    return OnboardingIntent.from_draft(
        OnboardingIntentDraft(
            source_repository="repository:smoeberg/kodegenerator",
            purpose=OnboardingPurpose.EXTEND,
            rationale="Carry one governed patch into delivery verification provenance.",
        ),
        declared_by="alice",
        organization_id="org-a",
        declared_at=datetime(2026, 9, 6, 11, 0, tzinfo=timezone.utc),
    )


def _onboarding(intent: OnboardingIntent) -> dict[str, object]:
    return {"intent": intent.canonical()}


def _audit(intent: OnboardingIntent) -> dict[str, object]:
    return {
        "report_id": "a" * 64,
        "authoritative": False,
        "recommendation": "CONTINUE_WITH_GAPS",
        "repository": intent.source_repository,
        "commit_sha": "b" * 40,
        "manifest_id": "c" * 64,
        "evidence_bundle_id": "d" * 64,
        "request_fingerprint": "e" * 64,
        "intent_id": intent.intent_id,
        "purpose": intent.purpose.value,
        "delivery_allowed": True,
        "findings": [],
        "maturity": [],
    }


def _proposal_chain():
    intent = _intent()
    onboarding = _onboarding(intent)
    audit = _audit(intent)
    plan = generate_project_plan(
        onboarding,
        audit,
        ProjectPlanningInput(
            objective="Add a governed delivery handoff",
            acceptance_criteria="The handoff is content-addressed and non-authoritative.",
            constraints="Do not trigger CI, Git push, release, or deployment.",
        ),
    )
    scope = ImplementationScope(
        allowed_paths=("README.md",),
        max_files=1,
        max_changed_lines=10,
    )
    instruction = default_implementation_instruction(plan)
    request = build_proposal_payload(
        onboarding_result=onboarding,
        audit_result=audit,
        plan_result=plan,
        instruction=instruction,
        scope=scope,
        command_id="proposal-command-delivery-1",
    )
    unified_diff = (
        "diff --git a/README.md b/README.md\n"
        "--- a/README.md\n"
        "+++ b/README.md\n"
        "@@ -1 +1 @@\n"
        "-old\n"
        "+new\n"
    )
    proposal_request_fingerprint = "f" * 64
    diff_sha256 = hashlib.sha256(unified_diff.encode("utf-8")).hexdigest()
    proposal_id = _digest(
        {
            "request_fingerprint": proposal_request_fingerprint,
            "provider_id": "provider.delivery-test",
            "diff_sha256": diff_sha256,
            "touched_paths": ["README.md"],
            "changed_lines": 2,
        }
    )
    proposal_result = {
        "request": request,
        "response": {
            "command_id": "proposal-command-delivery-1",
            "request_fingerprint": proposal_request_fingerprint,
            "authority_decision": "allow",
            "execution_status": "succeeded",
            "outcome_status": "succeeded",
            "proposal": {
                "proposal_id": proposal_id,
                "provider_id": "provider.delivery-test",
                "diff_sha256": diff_sha256,
                "touched_paths": ["README.md"],
                "changed_lines": 2,
                "unified_diff": unified_diff,
            },
        },
        "plan_id": plan["plan_id"],
        "plan_request_fingerprint": plan["request_fingerprint"],
        "authoritative": False,
        "applied": False,
    }
    return onboarding, audit, plan, proposal_result, proposal_id, diff_sha256


def _log(stream: str, content: str) -> dict[str, object]:
    sha256 = hashlib.sha256(content.encode("utf-8")).hexdigest()
    payload = {
        "stream": stream,
        "sha256": sha256,
        "byte_count": len(content.encode("utf-8")),
        "content": content,
        "truncated": False,
    }
    return {
        "artifact_id": _digest(payload),
        "sha256": sha256,
        "byte_count": payload["byte_count"],
        "content": content,
        "truncated": False,
    }


def _evidence(kind: str, artifact_id: str) -> dict[str, object]:
    stdout = _log("stdout", f"{kind} ok\n")
    stderr = _log("stderr", "")
    tool_fingerprint = _digest({"tool": kind, "version": 1})
    payload = {
        "tool_id": f"tool.{kind}",
        "kind": kind,
        "tool_fingerprint": tool_fingerprint,
        "artifact_id": artifact_id,
        "status": "passed",
        "exit_code": 0,
        "stdout_artifact_id": stdout["artifact_id"],
        "stderr_artifact_id": stderr["artifact_id"],
    }
    return {
        "evidence_id": _digest(payload),
        "tool_id": payload["tool_id"],
        "kind": kind,
        "tool_fingerprint": tool_fingerprint,
        "artifact_id": artifact_id,
        "status": "passed",
        "passed": True,
        "exit_code": 0,
        "stdout": stdout,
        "stderr": stderr,
    }


def _apply_result(proposal_id: str, diff_sha256: str) -> dict[str, object]:
    baseline = "1" * 64
    apply_request_fingerprint = "2" * 64
    toolchain_fingerprint = "3" * 64
    file_state = {
        "path": "README.md",
        "exists": True,
        "sha256": hashlib.sha256(b"new\n").hexdigest(),
        "byte_count": 4,
        "mode": 0o644,
    }
    artifact_payload = {
        "proposal_id": proposal_id,
        "diff_sha256": diff_sha256,
        "baseline_fingerprint": baseline,
        "files": [file_state],
    }
    artifact_id = _digest(artifact_payload)
    evidence = [
        _evidence("lint", artifact_id),
        _evidence("test", artifact_id),
        _evidence("build", artifact_id),
    ]
    record_payload = {
        "request_fingerprint": apply_request_fingerprint,
        "proposal_id": proposal_id,
        "baseline_fingerprint": baseline,
        "status": "succeeded",
        "artifact_id": artifact_id,
        "evidence_ids": [item["evidence_id"] for item in evidence],
        "committed": True,
        "rolled_back": False,
        "error": None,
    }
    return {
        "request": {
            "organization_id": "org-a",
            "command_id": "apply-command-delivery-1",
            "proposal_id": proposal_id,
        },
        "response": {
            "command_id": "apply-command-delivery-1",
            "proposal_id": proposal_id,
            "request_fingerprint": apply_request_fingerprint,
            "baseline_fingerprint": baseline,
            "toolchain_fingerprint": toolchain_fingerprint,
            "authority_decision": "allow",
            "execution_status": "succeeded",
            "outcome_status": "succeeded",
            "record_id": _digest(record_payload),
            "record_status": "succeeded",
            "committed": True,
            "rolled_back": False,
            "error": None,
            "artifact": {
                "artifact_id": artifact_id,
                **artifact_payload,
            },
            "evidence": evidence,
        },
        "proposal_id": proposal_id,
        "proposal_request_fingerprint": "f" * 64,
        "applied": True,
    }


def _chain():
    onboarding, audit, plan, proposal, proposal_id, diff_sha256 = _proposal_chain()
    apply = _apply_result(proposal_id, diff_sha256)
    return onboarding, audit, plan, proposal, apply


def test_candidate_is_deterministic_pending_and_never_authoritative() -> None:
    chain = _chain()

    first = build_delivery_verification_candidate(*chain)
    second = build_delivery_verification_candidate(*copy.deepcopy(chain))

    assert first.candidate_id == second.candidate_id
    assert first.status is DeliveryVerificationStatus.PENDING_AUTHORITATIVE_VERIFICATION
    assert first.authoritative is False
    assert first.verification_result is None
    canonical = first.canonical()
    assert canonical["status"] == "pending_authoritative_verification"
    assert canonical["authoritative"] is False
    assert canonical["verification_result"] is None
    assert len(canonical["evidence_ids"]) == 3


def test_candidate_binds_full_upstream_and_committed_apply_provenance() -> None:
    onboarding, audit, plan, proposal, apply = _chain()

    candidate = build_delivery_verification_candidate(
        onboarding, audit, plan, proposal, apply
    )

    assert candidate.organization_id == "org-a"
    assert candidate.repository == "repository:smoeberg/kodegenerator"
    assert candidate.intent_id == plan["provenance"]["intent_id"]
    assert candidate.audit_report_id == audit["report_id"]
    assert candidate.audit_commit_sha == audit["commit_sha"]
    assert candidate.plan_id == plan["plan_id"]
    assert candidate.proposal_id == apply["proposal_id"]
    assert candidate.apply_record_id == apply["response"]["record_id"]
    assert candidate.artifact_id == apply["response"]["artifact"]["artifact_id"]
    assert tuple(item.path for item in candidate.files) == ("README.md",)


def test_applied_flag_cannot_upgrade_failed_or_rolled_back_record() -> None:
    chain = list(_chain())
    apply = chain[-1]
    apply["response"]["record_status"] = "failed"
    apply["response"]["committed"] = False
    apply["response"]["rolled_back"] = True
    apply["response"]["error"] = "tool failed"

    with pytest.raises(DeliveryVerificationGUIError, match="successful patch record"):
        build_delivery_verification_candidate(*chain)


def test_tampered_committed_file_rejected_even_with_existing_artifact_id() -> None:
    chain = list(_chain())
    chain[-1]["response"]["artifact"]["files"][0]["sha256"] = "9" * 64

    with pytest.raises(DeliveryVerificationGUIError, match="artifact ID"):
        build_delivery_verification_candidate(*chain)


def test_tampered_tool_evidence_rejected_even_when_marked_passed() -> None:
    chain = list(_chain())
    chain[-1]["response"]["evidence"][0]["stdout"]["content"] = "tampered\n"

    with pytest.raises(DeliveryVerificationGUIError, match="stdout log artifact ID"):
        build_delivery_verification_candidate(*chain)


def test_tampered_patch_record_identity_rejected() -> None:
    chain = list(_chain())
    chain[-1]["response"]["record_id"] = "8" * 64

    with pytest.raises(DeliveryVerificationGUIError, match="Patch record ID"):
        build_delivery_verification_candidate(*chain)


def test_upstream_plan_tampering_rejected_before_delivery_candidate() -> None:
    chain = list(_chain())
    chain[2]["requirements"]["objective"] = "A different objective"

    with pytest.raises(DeliveryVerificationGUIError):
        build_delivery_verification_candidate(*chain)
