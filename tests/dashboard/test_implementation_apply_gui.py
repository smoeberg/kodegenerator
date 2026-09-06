"""Trust-boundary tests for proposal review and governed patch apply GUI."""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone

import pytest

from dashboard.implementation_apply import (
    ImplementationApplyGUIError,
    build_apply_payload,
    restore_apply_provenance,
    submit_governed_patch_apply,
)
from dashboard.implementation_proposal import (
    ImplementationScope,
    build_proposal_payload,
    default_implementation_instruction,
)
from dashboard.project_planning import (
    ProjectPlanningInput,
    generate_project_plan,
)
from phase4.onboarding import OnboardingIntent, OnboardingIntentDraft, OnboardingPurpose


def _digest(value: object) -> str:
    encoded = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _intent() -> OnboardingIntent:
    return OnboardingIntent.from_draft(
        OnboardingIntentDraft(
            source_repository="repository:smoeberg/kodegenerator",
            purpose=OnboardingPurpose.EXTEND,
            rationale="Continue through the exact governed implementation chain.",
        ),
        declared_by="alice",
        organization_id="org-a",
        declared_at=datetime(2026, 9, 6, 10, 0, tzinfo=timezone.utc),
    )


def _onboarding(intent: OnboardingIntent) -> dict[str, object]:
    return {"intent": intent.canonical()}


def _audit(intent: OnboardingIntent) -> dict[str, object]:
    return {
        "report_id": "report-apply-123",
        "authoritative": False,
        "recommendation": "CONTINUE_WITH_GAPS",
        "repository": intent.source_repository,
        "commit_sha": "a" * 40,
        "manifest_id": "manifest-apply-123",
        "evidence_bundle_id": "bundle-apply-123",
        "request_fingerprint": "audit-request-apply-123",
        "intent_id": intent.intent_id,
        "purpose": intent.purpose.value,
        "delivery_allowed": True,
        "findings": [],
        "maturity": [],
    }


def _plan(onboarding, audit) -> dict[str, object]:
    return generate_project_plan(
        onboarding,
        audit,
        ProjectPlanningInput(
            objective="Add the next governed feature",
            acceptance_criteria="The exact change is covered by deterministic tests.",
            constraints="Preserve the authority boundary.",
        ),
    )


def _proposal_chain():
    intent = _intent()
    onboarding = _onboarding(intent)
    audit = _audit(intent)
    plan = _plan(onboarding, audit)
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
        command_id="proposal-command-1",
    )
    unified_diff = (
        "diff --git a/README.md b/README.md\n"
        "--- a/README.md\n"
        "+++ b/README.md\n"
        "@@ -1 +1 @@\n"
        "-old\n"
        "+new\n"
    )
    request_fingerprint = "b" * 64
    diff_sha256 = hashlib.sha256(unified_diff.encode("utf-8")).hexdigest()
    proposal_id = _digest(
        {
            "request_fingerprint": request_fingerprint,
            "provider_id": "provider.test",
            "diff_sha256": diff_sha256,
            "touched_paths": ["README.md"],
            "changed_lines": 2,
        }
    )
    response = {
        "command_id": "proposal-command-1",
        "request_fingerprint": request_fingerprint,
        "authority_decision": "allow",
        "execution_status": "succeeded",
        "outcome_status": "succeeded",
        "proposal": {
            "proposal_id": proposal_id,
            "provider_id": "provider.test",
            "diff_sha256": diff_sha256,
            "touched_paths": ["README.md"],
            "changed_lines": 2,
            "unified_diff": unified_diff,
        },
    }
    result = {
        "request": request,
        "response": response,
        "plan_id": plan["plan_id"],
        "plan_request_fingerprint": plan["request_fingerprint"],
        "authoritative": False,
        "applied": False,
    }
    return onboarding, audit, plan, result


def _successful_apply_response(proposal_id: str, diff_sha256: str) -> dict[str, object]:
    artifact_id = "1" * 64
    baseline = "c" * 64
    evidence = [
        {
            "evidence_id": character * 64,
            "tool_id": f"tool.{kind}",
            "kind": kind,
            "tool_fingerprint": character * 64,
            "artifact_id": artifact_id,
            "status": "passed",
            "passed": True,
            "exit_code": 0,
        }
        for kind, character in (("lint", "2"), ("test", "3"), ("build", "4"))
    ]
    return {
        "command_id": "apply-command-1",
        "proposal_id": proposal_id,
        "request_fingerprint": "5" * 64,
        "baseline_fingerprint": baseline,
        "toolchain_fingerprint": "6" * 64,
        "authority_decision": "allow",
        "execution_status": "succeeded",
        "outcome_status": "succeeded",
        "record_id": "7" * 64,
        "record_status": "succeeded",
        "committed": True,
        "rolled_back": False,
        "error": None,
        "artifact": {
            "artifact_id": artifact_id,
            "proposal_id": proposal_id,
            "diff_sha256": diff_sha256,
            "baseline_fingerprint": baseline,
            "files": [{"path": "README.md"}],
        },
        "evidence": evidence,
    }


def test_restore_apply_provenance_revalidates_exact_proposal_identity() -> None:
    onboarding, audit, plan, result = _proposal_chain()

    restored = restore_apply_provenance(onboarding, audit, plan, result)

    assert restored.organization_id == "org-a"
    assert restored.resource == "repository:smoeberg/kodegenerator"
    assert restored.touched_paths == ("README.md",)
    assert restored.unified_diff.endswith("\n")
    assert len(restored.proposal_id) == 64


def test_restore_apply_rejects_tampered_diff_even_when_proposal_id_is_unchanged() -> None:
    onboarding, audit, plan, result = _proposal_chain()
    result["response"]["proposal"]["unified_diff"] += "+tampered\n"

    with pytest.raises(ImplementationApplyGUIError, match="SHA-256"):
        restore_apply_provenance(onboarding, audit, plan, result)


def test_restore_apply_rejects_tampered_upstream_proposal_request() -> None:
    onboarding, audit, plan, result = _proposal_chain()
    result["request"]["resource"] = "repository:other/project"

    with pytest.raises(ImplementationApplyGUIError, match="upstream provenance"):
        restore_apply_provenance(onboarding, audit, plan, result)


def test_restore_apply_rejects_rebound_proposal_content_identity() -> None:
    onboarding, audit, plan, result = _proposal_chain()
    result["response"]["proposal"]["proposal_id"] = "f" * 64

    with pytest.raises(ImplementationApplyGUIError, match="content identity"):
        restore_apply_provenance(onboarding, audit, plan, result)


def test_apply_payload_contains_only_tenant_command_and_proposal_identity() -> None:
    onboarding, audit, plan, result = _proposal_chain()
    proposal = restore_apply_provenance(onboarding, audit, plan, result)

    payload = build_apply_payload(proposal, command_id="apply-command-1")

    assert payload == {
        "organization_id": "org-a",
        "command_id": "apply-command-1",
        "proposal_id": proposal.proposal_id,
    }
    assert "baseline" not in payload
    assert "tools" not in payload
    assert "command" not in payload


def test_submit_apply_calls_only_governed_execution_endpoint_and_accepts_success() -> None:
    onboarding, audit, plan, result = _proposal_chain()
    proposal = restore_apply_provenance(onboarding, audit, plan, result)
    response = _successful_apply_response(proposal.proposal_id, proposal.diff_sha256)

    class Client:
        def __init__(self):
            self.calls = []

        def post(self, path, *, json):
            self.calls.append((path, json))
            return response

    client = Client()
    applied = submit_governed_patch_apply(
        client,
        proposal=proposal,
        command_id="apply-command-1",
    )

    assert client.calls[0][0] == "/implementation-agent/executions"
    assert applied["applied"] is True
    assert applied["response"]["record_status"] == "succeeded"


def test_successful_apply_requires_all_three_passing_evidence_classes() -> None:
    onboarding, audit, plan, result = _proposal_chain()
    proposal = restore_apply_provenance(onboarding, audit, plan, result)
    response = _successful_apply_response(proposal.proposal_id, proposal.diff_sha256)
    response["evidence"] = response["evidence"][:-1]

    class Client:
        def post(self, _path, *, json):
            assert json["proposal_id"] == proposal.proposal_id
            return response

    with pytest.raises(ImplementationApplyGUIError, match="lint, test og build"):
        submit_governed_patch_apply(
            Client(),
            proposal=proposal,
            command_id="apply-command-1",
        )


def test_failed_apply_is_preserved_as_not_committed() -> None:
    onboarding, audit, plan, result = _proposal_chain()
    proposal = restore_apply_provenance(onboarding, audit, plan, result)
    response = {
        **_successful_apply_response(proposal.proposal_id, proposal.diff_sha256),
        "execution_status": "failed",
        "outcome_status": "failed",
        "record_status": "failed",
        "committed": False,
        "rolled_back": True,
        "error": "trusted test failed",
        "artifact": None,
        "evidence": [],
    }

    class Client:
        def post(self, _path, *, json):
            assert json["proposal_id"] == proposal.proposal_id
            return response

    applied = submit_governed_patch_apply(
        Client(),
        proposal=proposal,
        command_id="apply-command-1",
    )

    assert applied["applied"] is False
    assert applied["response"]["rolled_back"] is True
