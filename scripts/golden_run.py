"""Two-phase, provider-backed Golden Real Run for the certified DOR demo.

The harness deliberately preserves the human review boundary:

* ``prepare`` executes onboarding, read-only audit, deterministic planning and a
  real Implementation Agent proposal, then stops.
* ``apply`` requires the exact proposal id selected by the operator before it
  may request governed patch application, Delivery Contract certification and
  requirement traceability.
* ``acceptance`` is a fixed benchmark oracle executed inside the API container
  against the governed patch workspace.  It is not release/merge/deploy
  authority.
* ``finalize`` combines governed evidence and the fixed oracle into one local,
  content-addressed benchmark report.

No command prints or persists credentials or bearer tokens.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import subprocess
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping


CONTRACT_ID = "dor.golden_real_run.v1"
CONTRACT_VERSION = "1.0"
DEMO_ORGANIZATION = "dor-demo-org"
DEMO_REPOSITORY = "repository:demo/golden"
EXPECTED_STATUS = {"status": "ok", "version": "1.0.0"}
OBJECTIVE = "Extend app.status() so the returned status document includes version 1.0.0 while preserving status ok."
ACCEPTANCE_CRITERIA = (
    'Calling app.status() returns exactly {"status": "ok", "version": "1.0.0"}.'
)
RATIONALE = "Golden Real Run v1: exercise the canonical governed delivery chain on the certified demo repository."
ALLOWED_PATHS = ("app.py",)
MAX_FILES = 1
MAX_CHANGED_LINES = 20


class GoldenRunError(RuntimeError):
    """Raised when the Golden Run cannot preserve its canonical contract."""


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: datetime | None = None) -> str:
    return (value or _now()).isoformat()


def _parse_time(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        raise GoldenRunError("benchmark timestamps must be timezone-aware")
    return parsed


def _seconds(start: str, end: str) -> float:
    return round((_parse_time(end) - _parse_time(start)).total_seconds(), 6)


def _canonical_digest(payload: Mapping[str, Any]) -> str:
    encoded = json.dumps(
        dict(payload),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def scenario() -> dict[str, Any]:
    payload = {
        "contract_id": CONTRACT_ID,
        "contract_version": CONTRACT_VERSION,
        "organization_id": DEMO_ORGANIZATION,
        "repository": DEMO_REPOSITORY,
        "objective": OBJECTIVE,
        "acceptance_criteria": ACCEPTANCE_CRITERIA,
        "constraints": "",
        "scope": {
            "allowed_paths": list(ALLOWED_PATHS),
            "max_files": MAX_FILES,
            "max_changed_lines": MAX_CHANGED_LINES,
        },
        "expected_status": EXPECTED_STATUS,
    }
    return {**payload, "scenario_fingerprint": _canonical_digest(payload)}


def _command_id(stage: str) -> str:
    return f"golden-{stage}-{uuid.uuid4()}"


def _client():
    from dashboard.api_client import DORAPIClient

    password = os.environ.get("DOR_ADMIN_PASSWORD", "").strip()
    if not password:
        raise GoldenRunError("DOR_ADMIN_PASSWORD is required inside the demo dashboard")
    username = os.environ.get("DOR_ADMIN_USERNAME", "admin").strip() or "admin"
    client = DORAPIClient()
    client.login(username, password)
    return client, username


def prepare() -> dict[str, Any]:
    """Run through a real provider-backed proposal and stop for human review."""
    from dashboard.implementation_proposal import (
        ImplementationScope,
        default_implementation_instruction,
        submit_implementation_proposal,
    )
    from dashboard.project_audit import execute_project_audit, restore_onboarding_intent
    from dashboard.project_planning import ProjectPlanningInput, generate_project_plan
    from dashboard.repository_checkout_catalog import discover_repository_checkout

    started_at = _iso()
    started_clock = time.perf_counter()
    client, username = _client()

    onboarding_payload = {
        "command_id": _command_id("onboarding"),
        "source_repository": DEMO_REPOSITORY,
        "purpose": "extend",
        "rationale": RATIONALE,
        "target_stack": None,
        "supersedes_intent_id": None,
    }
    onboarding = client.post(
        "/api/v1/control-plane/onboarding-intents",
        json=onboarding_payload,
    )
    if not isinstance(onboarding, Mapping):
        raise GoldenRunError("onboarding API returned a non-object")
    intent = restore_onboarding_intent(onboarding)
    if intent.organization_id != DEMO_ORGANIZATION or intent.source_repository != DEMO_REPOSITORY:
        raise GoldenRunError("onboarding identity drifted from the golden scenario")

    binding = discover_repository_checkout(
        organization_id=DEMO_ORGANIZATION,
        repository=DEMO_REPOSITORY,
    )
    audit = execute_project_audit(intent, binding)
    requirements = ProjectPlanningInput(
        objective=OBJECTIVE,
        acceptance_criteria=ACCEPTANCE_CRITERIA,
        constraints="",
    )
    plan = generate_project_plan(onboarding, audit, requirements)
    scope = ImplementationScope(
        allowed_paths=ALLOWED_PATHS,
        max_files=MAX_FILES,
        max_changed_lines=MAX_CHANGED_LINES,
    )
    instruction = default_implementation_instruction(plan)

    provider_started = time.perf_counter()
    proposal = submit_implementation_proposal(
        client,
        onboarding_result=onboarding,
        audit_result=audit,
        plan_result=plan,
        instruction=instruction,
        scope=scope,
        command_id=_command_id("proposal"),
    )
    provider_seconds = round(time.perf_counter() - provider_started, 6)

    response = proposal.get("response")
    artifact = response.get("proposal") if isinstance(response, Mapping) else None
    proposal_id = artifact.get("proposal_id") if isinstance(artifact, Mapping) else None
    if not isinstance(proposal_id, str) or len(proposal_id) != 64:
        raise GoldenRunError("proposal response did not contain a canonical proposal id")
    touched = artifact.get("touched_paths") if isinstance(artifact, Mapping) else None
    if touched != ["app.py"]:
        raise GoldenRunError("golden proposal must touch exactly app.py")

    prepared_at = _iso()
    report = {
        "schema_version": 1,
        "contract_id": CONTRACT_ID,
        "contract_version": CONTRACT_VERSION,
        "classification": "AWAITING_APPLY_APPROVAL",
        "scenario": scenario(),
        "operator": username,
        "started_at": started_at,
        "prepared_at": prepared_at,
        "timing": {
            "prepare_seconds": round(time.perf_counter() - started_clock, 6),
            "provider_proposal_seconds": provider_seconds,
        },
        "onboarding": dict(onboarding),
        "audit": dict(audit),
        "plan": dict(plan),
        "proposal": dict(proposal),
        "approval": {
            "required": True,
            "approved": False,
            "proposal_id": proposal_id,
        },
        "authority": {
            "semantic_oracle_authoritative": False,
            "release_authority": False,
            "merge_authority": False,
            "deploy_authority": False,
        },
    }
    report["run_id"] = _canonical_digest(
        {
            "scenario_fingerprint": report["scenario"]["scenario_fingerprint"],
            "audit_commit_sha": audit["commit_sha"],
            "plan_id": plan["plan_id"],
            "proposal_id": proposal_id,
        }
    )
    return report


def _load_json(path: str) -> dict[str, Any]:
    if path == "-":
        raw = sys.stdin.read()
    else:
        raw = Path(path).read_text(encoding="utf-8")
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise GoldenRunError(f"invalid golden run JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise GoldenRunError("golden run input must be a JSON object")
    return payload


def _require_prepared(report: Mapping[str, Any]) -> None:
    if report.get("contract_id") != CONTRACT_ID or report.get("contract_version") != CONTRACT_VERSION:
        raise GoldenRunError("golden run contract mismatch")
    if report.get("classification") != "AWAITING_APPLY_APPROVAL":
        raise GoldenRunError("input is not awaiting apply approval")
    if report.get("scenario") != scenario():
        raise GoldenRunError("golden scenario drifted")


def apply(prepared: Mapping[str, Any], *, proposal_id: str) -> dict[str, Any]:
    """Apply only the exact operator-approved proposal, then certify and trace it."""
    from dashboard.delivery_verification import build_delivery_verification_candidate
    from dashboard.implementation_apply import (
        restore_apply_provenance,
        submit_governed_patch_apply,
    )

    _require_prepared(prepared)
    approval = prepared.get("approval")
    expected_id = approval.get("proposal_id") if isinstance(approval, Mapping) else None
    if proposal_id != expected_id:
        raise GoldenRunError(
            "operator approval must name the exact prepared 64-character proposal id"
        )

    apply_started_at = _iso()
    apply_started_clock = time.perf_counter()
    client, username = _client()
    onboarding = prepared["onboarding"]
    audit = prepared["audit"]
    plan = prepared["plan"]
    proposal_result = prepared["proposal"]

    proposal = restore_apply_provenance(
        onboarding,
        audit,
        plan,
        proposal_result,
    )
    if proposal.proposal_id != proposal_id or proposal.touched_paths != ("app.py",):
        raise GoldenRunError("approved proposal content no longer matches the prepared scope")

    apply_result = submit_governed_patch_apply(
        client,
        proposal=proposal,
        command_id=_command_id("apply"),
    )
    if apply_result.get("applied") is not True:
        raise GoldenRunError("governed patch apply did not commit the proposal")

    candidate = build_delivery_verification_candidate(
        onboarding,
        audit,
        plan,
        proposal_result,
        apply_result,
    )
    candidate_payload = candidate.canonical()

    certification = client.post(
        "/api/v1/control-plane/delivery-certificates",
        json={
            "command_id": _command_id("certificate"),
            "organization_id": DEMO_ORGANIZATION,
            "candidate": candidate_payload,
        },
    )
    certificate = certification.get("certificate") if isinstance(certification, Mapping) else None
    if not isinstance(certificate, Mapping):
        raise GoldenRunError("delivery certification returned no certificate")
    if certificate.get("result") != "pass":
        raise GoldenRunError(
            "Delivery Contract did not PASS: " + ",".join(certificate.get("reason_codes") or [])
        )
    certificate_id = certificate.get("certificate_id")
    if not isinstance(certificate_id, str) or len(certificate_id) != 64:
        raise GoldenRunError("delivery certificate id is not canonical")

    artifact_paths = [item["path"] for item in candidate_payload["files"]]
    evidence_ids = list(candidate_payload["evidence_ids"])
    structural_rationale = (
        "Golden Run structural link to the exact certified changed artifact and fixed tool evidence; "
        "this is not a semantic-satisfaction claim."
    )
    traceability = client.post(
        "/api/v1/control-plane/requirement-traceability",
        json={
            "command_id": _command_id("traceability"),
            "organization_id": DEMO_ORGANIZATION,
            "certificate_id": certificate_id,
            "plan_id": plan["plan_id"],
            "planning_provenance": plan["provenance"],
            "requirements": plan["requirements"],
            "links": [
                {
                    "kind": "objective",
                    "artifact_paths": artifact_paths,
                    "evidence_ids": evidence_ids,
                    "rationale": structural_rationale,
                },
                {
                    "kind": "acceptance_criteria",
                    "artifact_paths": artifact_paths,
                    "evidence_ids": evidence_ids,
                    "rationale": structural_rationale,
                },
            ],
        },
    )
    manifest = traceability.get("manifest") if isinstance(traceability, Mapping) else None
    if not isinstance(manifest, Mapping) or manifest.get("status") != "complete":
        raise GoldenRunError("golden traceability did not reach COMPLETE")

    governed_completed_at = _iso()
    result = dict(prepared)
    result.update(
        {
            "classification": "GOVERNED_CHAIN_COMPLETE",
            "apply_started_at": apply_started_at,
            "governed_completed_at": governed_completed_at,
            "apply": dict(apply_result),
            "candidate": candidate_payload,
            "certification": dict(certification),
            "traceability": dict(traceability),
            "approval": {
                "required": True,
                "approved": True,
                "proposal_id": proposal_id,
                "approved_by": username,
                "approved_at": apply_started_at,
            },
            "timing": {
                **dict(prepared.get("timing") or {}),
                "human_approval_wait_seconds": _seconds(
                    str(prepared["prepared_at"]), apply_started_at
                ),
                "apply_certificate_traceability_seconds": round(
                    time.perf_counter() - apply_started_clock, 6
                ),
                "intent_to_delivery_pass_seconds": _seconds(
                    str(prepared["started_at"]), governed_completed_at
                ),
            },
        }
    )
    return result


def acceptance_probe(workspace: Path) -> dict[str, Any]:
    """Execute the fixed v1 semantic benchmark oracle against the patch workspace."""
    checked_at = _iso()
    root = workspace.resolve()
    app_file = root / "app.py"
    if not app_file.is_file():
        return {
            "classification": "REJECTED",
            "checked_at": checked_at,
            "reason": "app.py is missing from the governed patch workspace",
            "semantic_observed": False,
            "authority_scope": "golden_benchmark_oracle_only",
        }
    try:
        spec = importlib.util.spec_from_file_location("dor_golden_app", app_file)
        if spec is None or spec.loader is None:
            raise GoldenRunError("cannot load app.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        value = module.status()
    except Exception as exc:  # fixed local benchmark probe; error is evidence, not authority.
        return {
            "classification": "REJECTED",
            "checked_at": checked_at,
            "reason": f"fixed acceptance probe failed: {type(exc).__name__}",
            "semantic_observed": False,
            "authority_scope": "golden_benchmark_oracle_only",
        }

    completed = subprocess.run(
        ["git", "diff", "--name-only", "HEAD"],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )
    changed_paths = sorted(
        line.strip() for line in completed.stdout.splitlines() if line.strip()
    )
    accepted = value == EXPECTED_STATUS and changed_paths == ["app.py"]
    return {
        "classification": "ACCEPTED" if accepted else "REJECTED",
        "checked_at": checked_at,
        "semantic_observed": accepted,
        "observed_status": value,
        "expected_status": EXPECTED_STATUS,
        "changed_paths": changed_paths,
        "app_sha256": hashlib.sha256(app_file.read_bytes()).hexdigest(),
        "authority_scope": "golden_benchmark_oracle_only",
        "release_authority": False,
        "merge_authority": False,
        "deploy_authority": False,
    }


def finalize_reports(
    governed: Mapping[str, Any], acceptance: Mapping[str, Any]
) -> dict[str, Any]:
    if governed.get("contract_id") != CONTRACT_ID:
        raise GoldenRunError("governed report contract mismatch")
    if governed.get("classification") != "GOVERNED_CHAIN_COMPLETE":
        raise GoldenRunError("governed chain is not complete")
    certificate = governed.get("certification", {}).get("certificate", {})
    manifest = governed.get("traceability", {}).get("manifest", {})
    accepted = (
        acceptance.get("classification") == "ACCEPTED"
        and acceptance.get("semantic_observed") is True
    )
    passed = certificate.get("result") == "pass" and manifest.get("status") == "complete" and accepted
    completed_at = str(acceptance.get("checked_at") or _iso())
    result = {
        "schema_version": 1,
        "contract_id": CONTRACT_ID,
        "contract_version": CONTRACT_VERSION,
        "classification": "GOLDEN_RUN_PASS" if passed else "GOLDEN_RUN_FAIL",
        "run_id": governed.get("run_id"),
        "scenario": governed.get("scenario"),
        "started_at": governed.get("started_at"),
        "completed_at": completed_at,
        "metrics": {
            "intent_to_verified_behavior_seconds": _seconds(
                str(governed["started_at"]), completed_at
            ),
            "intent_to_delivery_pass_seconds": governed.get("timing", {}).get(
                "intent_to_delivery_pass_seconds"
            ),
            "human_approval_wait_seconds": governed.get("timing", {}).get(
                "human_approval_wait_seconds"
            ),
            "provider_proposal_seconds": governed.get("timing", {}).get(
                "provider_proposal_seconds"
            ),
            "prepare_seconds": governed.get("timing", {}).get("prepare_seconds"),
            "apply_certificate_traceability_seconds": governed.get("timing", {}).get(
                "apply_certificate_traceability_seconds"
            ),
        },
        "results": {
            "proposal_id": governed.get("approval", {}).get("proposal_id"),
            "apply_record_id": governed.get("candidate", {}).get("apply_record_id"),
            "candidate_id": governed.get("candidate", {}).get("candidate_id"),
            "certificate_id": certificate.get("certificate_id"),
            "delivery_certificate_result": certificate.get("result"),
            "traceability_manifest_id": manifest.get("manifest_id"),
            "traceability_status": manifest.get("status"),
            "fixed_semantic_oracle": dict(acceptance),
        },
        "authority": {
            "delivery_certificate_authority_scope": "delivery_contract_v1",
            "traceability_authoritative": False,
            "semantic_oracle_authority_scope": "golden_benchmark_oracle_only",
            "release_authority": False,
            "merge_authority": False,
            "deploy_authority": False,
        },
    }
    unsigned = dict(result)
    result["evidence_id"] = _canonical_digest(unsigned)
    return result


def review(report: Mapping[str, Any]) -> None:
    proposal = report.get("proposal", {}).get("response", {}).get("proposal", {})
    proposal_id = proposal.get("proposal_id", "")
    print(f"Classification: {report.get('classification')}")
    print(f"Run ID: {report.get('run_id')}")
    print(f"Proposal ID: {proposal_id}")
    print("Touched paths: " + ", ".join(proposal.get("touched_paths") or []))
    print(f"Changed lines: {proposal.get('changed_lines')}")
    print("\n--- REVIEW THIS EXACT DIFF ---")
    print(proposal.get("unified_diff") or "")
    print("--- END DIFF ---\n")
    print(
        "To approve exactly this proposal: "
        f"make demo-golden-apply PROPOSAL_ID={proposal_id}"
    )


def review_final(report: Mapping[str, Any]) -> None:
    metrics = report.get("metrics") or {}
    results = report.get("results") or {}
    print(f"Classification: {report.get('classification')}")
    print(f"Evidence ID: {report.get('evidence_id')}")
    print(f"IVB seconds: {metrics.get('intent_to_verified_behavior_seconds')}")
    print(f"Delivery certificate: {results.get('delivery_certificate_result')}")
    print(f"Traceability: {results.get('traceability_status')}")
    oracle = results.get("fixed_semantic_oracle") or {}
    print(f"Fixed semantic oracle: {oracle.get('classification')}")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the certified DOR Golden Real Run v1")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("prepare")

    apply_parser = sub.add_parser("apply")
    apply_parser.add_argument("--input", default="-")
    apply_parser.add_argument("--proposal-id", required=True)

    acceptance_parser = sub.add_parser("acceptance")
    acceptance_parser.add_argument(
        "--workspace", type=Path, default=Path("/demo/patch-workspace")
    )

    finalize_parser = sub.add_parser("finalize")
    finalize_parser.add_argument("--governed", required=True)
    finalize_parser.add_argument("--acceptance", required=True)

    review_parser = sub.add_parser("review")
    review_parser.add_argument("--input", required=True)

    final_review_parser = sub.add_parser("review-final")
    final_review_parser.add_argument("--input", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "prepare":
            payload = prepare()
        elif args.command == "apply":
            payload = apply(_load_json(args.input), proposal_id=args.proposal_id)
        elif args.command == "acceptance":
            payload = acceptance_probe(args.workspace)
        elif args.command == "finalize":
            payload = finalize_reports(
                _load_json(args.governed),
                _load_json(args.acceptance),
            )
        elif args.command == "review":
            review(_load_json(args.input))
            return 0
        else:
            review_final(_load_json(args.input))
            return 0
    except (GoldenRunError, OSError, KeyError, TypeError, ValueError) as exc:
        print(
            json.dumps(
                {
                    "classification": "ERROR",
                    "contract_id": CONTRACT_ID,
                    "errors": [str(exc)],
                },
                indent=2,
                sort_keys=True,
            )
        )
        return 1

    print(json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False))
    if payload.get("classification") in {
        "AWAITING_APPLY_APPROVAL",
        "GOVERNED_CHAIN_COMPLETE",
        "ACCEPTED",
        "GOLDEN_RUN_PASS",
    }:
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
