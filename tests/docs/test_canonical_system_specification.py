from __future__ import annotations

import json
from pathlib import Path


SPEC_PATH = Path("docs/CANONICAL_SYSTEM_SPECIFICATION.md")
STATE_PATH = Path("docs/CURRENT_STATE.json")


def test_canonical_system_specification_declares_required_authority_boundaries() -> None:
    text = SPEC_PATH.read_text(encoding="utf-8")

    required_markers = (
        "# Canonical System Specification v1",
        "## 2. Canonical system shape",
        "## 3. System-wide invariants",
        "## 4. Canonical delivery stages",
        "## 5. Tenant and process boundary",
        "## 6. Authority interpretation matrix",
        "Audit recommendation != PASS",
        "Plan proposal != execution authority",
        "Patch proposal != apply authority",
        "Delivery Verification Candidate != Delivery PASS",
        "Delivery Certificate PASS != release/merge/deploy authority",
        "Traceability COMPLETE != semantic requirement satisfaction",
        "Artifact Acceptance ACCEPTED != release/merge/deploy/execution authority",
        'authority_scope="multi_spec_artifact_acceptance"',
        "machine_semantic_verification=null",
    )
    for marker in required_markers:
        assert marker in text, f"canonical system specification missing: {marker}"


def test_canonical_system_specification_references_existing_normative_surfaces() -> None:
    referenced_paths = (
        "AGENTS.md",
        "SECURITY.md",
        "docs/PHASE4_ARCHITECTURE.md",
        "docs/ARCHITECTURE_CONTRACT_V1.md",
        "docs/GOVERNED_PATCH_APPLY_GUI.md",
        "docs/DELIVERY_VERIFICATION_HANDOFF.md",
        "docs/DELIVERY_CERTIFICATE.md",
        "docs/REQUIREMENT_ARTIFACT_TRACEABILITY.md",
        "docs/DEPLOYMENT_AND_RELEASE.md",
        "docs/DEPLOY_SECRET_ISOLATION.md",
        "phase4/artifact_acceptance.py",
        "api/main.py",
        "api/api_surface.py",
        "dashboard/pages/01_Onboarding.py",
        "dashboard/pages/02_Project_Audit.py",
        "dashboard/pages/03_Requirements_And_Plan.py",
        "dashboard/pages/04_Implementation_Proposal.py",
        "dashboard/pages/05_Patch_Review_And_Apply.py",
        "dashboard/pages/06_Delivery_Verification_Handoff.py",
        "dashboard/pages/07_Delivery_Certificate.py",
        "dashboard/pages/08_Requirement_Artifact_Traceability.py",
        "dashboard/pages/09_Multi_Spec_Artifact_Acceptance.py",
    )
    for path in referenced_paths:
        assert Path(path).exists(), f"canonical system specification references missing path: {path}"


def test_current_state_points_to_canonical_system_spec_and_closes_roadmap_item() -> None:
    state = json.loads(STATE_PATH.read_text(encoding="utf-8"))

    assert state["canonical_system_specification"] == str(SPEC_PATH)
    assert "canonical_system_specification" not in state["open_work"]
    assert state["canonical_alembic_head"] == "032_work_unit_revisions"
