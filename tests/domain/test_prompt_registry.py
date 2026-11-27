"""Decision 42: prompts are versioned data, not code."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from domain.prompt_registry import (
    PROMPTS_PATH,
    PromptRegistry,
    PromptRegistryError,
    PromptStatus,
    default_registry,
)
from domain.role_process import RoleKind, default_catalog
from execution import architecture_council, contract_council, package_control


def copy(tmp_path: Path) -> Path:
    root = tmp_path / "prompts"
    shutil.copytree(PROMPTS_PATH, root)
    return root


def write(
    root: Path,
    role: str,
    name: str,
    header: str,
    text: str = "You are the role. Untrusted input.\n",
) -> Path:
    path = root / role / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"---\n{header}\n---\n{text}")
    return path


def test_every_prompt_belongs_to_an_agent_role_and_has_one_active_version() -> None:
    registry = default_registry()
    catalog = default_catalog()
    assert registry.purposes()
    for role, purpose in registry.purposes():
        assert catalog.role(role).kind is RoleKind.AGENT
        active = registry.active(role, purpose)
        assert (
            active.status is PromptStatus.ACTIVE
            and active.approved_by == "project_board"
        )
        assert active.ref.startswith(f"{role}/{purpose}@v{active.version}+")


def test_the_code_runs_on_the_registry_prompts() -> None:
    registry = default_registry()
    assert (
        architecture_council.ARCHITECTURE_DIALOGUE.proposer_instructions
        == registry.active("architect", "propose_architecture").text
    )
    assert (
        contract_council.CONTRACT_DIALOGUE.reviewer_prompt_version
        == registry.active("context_controller", "review_contracts").ref
    )
    assert (
        package_control.LEVEL1_INSTRUCTIONS
        == registry.active("code_auditor", "audit_package").text
    )


def test_a_proposed_version_waits_and_needs_no_approval(tmp_path) -> None:
    root = copy(tmp_path)
    write(
        root,
        "architect",
        "propose_architecture.v2.md",
        "role: architect\npurpose: propose_architecture\nversion: 2\nstatus: proposed",
    )
    registry = PromptRegistry.load(root)
    assert registry.active("architect", "propose_architecture").version == 1
    assert registry.next_version("architect", "propose_architecture") == 3


@pytest.mark.parametrize(
    ("role", "name", "header", "message"),
    [
        (
            "architect",
            "propose_architecture.v2.md",
            "role: architect\npurpose: propose_architecture\nversion: 2\nstatus: active",
            "approval",
        ),
        (
            "architect",
            "propose_architecture.v2.md",
            "role: architect\npurpose: propose_architecture\nversion: 2\nstatus: active\napproved_by: project_manager\napproval_ref: x",
            "approval",
        ),
        (
            "architect",
            "propose_architecture.v2.md",
            "role: architect\npurpose: propose_architecture\nversion: 2\nstatus: active\napproved_by: project_board\napproval_ref: PR",
            "exactly one active",
        ),
        (
            "architect",
            "propose_architecture.v3.md",
            "role: architect\npurpose: propose_architecture\nversion: 2\nstatus: proposed",
            "file name",
        ),
        (
            "fact_check",
            "check.v1.md",
            "role: fact_check\npurpose: check\nversion: 1\nstatus: active\napproved_by: project_board\napproval_ref: PR",
            "not an agent role",
        ),
        (
            "ghost",
            "x.v1.md",
            "role: ghost\npurpose: x\nversion: 1\nstatus: active\napproved_by: project_board\napproval_ref: PR",
            "not an agent role",
        ),
        (
            "coder",
            "implement.v1.md",
            "role: coder\npurpose: implement\nversion: 1\nstatus: proposed",
            "exactly one active",
        ),
        (
            "architect",
            "propose_architecture.v2.md",
            "role: architect\npurpose: propose_architecture\nversion: 2\nstatus: live",
            "invalid header",
        ),
    ],
)
def test_an_inconsistent_registry_fails_closed(
    tmp_path, role, name, header, message
) -> None:
    root = copy(tmp_path)
    write(root, role, name, header)
    with pytest.raises(PromptRegistryError, match=message):
        PromptRegistry.load(root)


def test_a_trial_version_runs_beside_the_active_one(tmp_path) -> None:
    root = copy(tmp_path)
    write(
        root,
        "architect",
        "propose_architecture.v2.md",
        "role: architect\npurpose: propose_architecture\nversion: 2\nstatus: trial\napproved_by: project_board\napproval_ref: PR",
    )
    registry = PromptRegistry.load(root)
    assert registry.trial("architect", "propose_architecture").version == 2
    write(
        root,
        "architect",
        "propose_architecture.v3.md",
        "role: architect\npurpose: propose_architecture\nversion: 3\nstatus: trial\napproved_by: project_board\napproval_ref: PR",
    )
    with pytest.raises(PromptRegistryError, match="trial"):
        PromptRegistry.load(root)
