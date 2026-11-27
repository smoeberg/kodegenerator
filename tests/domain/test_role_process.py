"""Foundation principle: DOR is role-process logic (plan decision 39).

Any agent may hold any role; a role is a prompt plus a context packet in a
fresh job. On the same work package a control role must come from a
different producer (brand) and run in a different session than the role it
controls. The catalog is data and fails closed when inconsistent.
"""

from __future__ import annotations

import copy

import pytest
import yaml

from domain.agent_job import AgentIdentity
from domain.pipeline_task_mapping import PipelineTaskMapping
from domain.role_process import (
    CATALOG_PATH,
    REQUIRED_INDEPENDENCE_LEVEL,
    RoleAssignment,
    RoleAuthority,
    RoleKind,
    RoleLayer,
    RoleProcessError,
    default_catalog,
    parse_catalog,
    validate_assignment,
)
from phase4.council.configuration import IndependenceLevel
from runtime.pipeline_orchestrator import PipelineOrchestrator


def _role(data: dict, role_id: str) -> dict:
    return next(r for r in data["roles"] if r["id"] == role_id)


def _raw() -> dict:
    return yaml.safe_load(CATALOG_PATH.read_text(encoding="utf-8"))


def _assign(
    job: str, role: str, brand: str | None, session: str | None, package: str = "wp-1"
):
    return RoleAssignment(
        job_id=job,
        work_package_id=package,
        role_id=role,
        brand=brand,
        session_id=session,
    )


# --------------------------------------------------------------------- #
# Catalog
# --------------------------------------------------------------------- #
def test_required_level_is_the_existing_brand_independence_level() -> None:
    assert REQUIRED_INDEPENDENCE_LEVEL == IndependenceLevel.BRAND.value


def test_catalog_loads_and_every_agent_output_is_controlled() -> None:
    catalog = default_catalog()
    assert catalog.version == 2
    for spec in catalog.roles.values():
        if spec.kind is RoleKind.AGENT:
            assert "fact_check" in spec.controlled_by, spec.id
            assert spec.id not in spec.controlled_by
    coder = catalog.role("coder")
    assert {
        "code_auditor",
        "context_controller",
        "test_designer",
        "security_reviewer",
    } <= set(coder.controlled_by)


def test_governance_layer_steers_and_only_the_human_decides() -> None:
    """Decision 40: PRINCE2 Agile; the project board is the only decider."""
    catalog = default_catalog()
    deciders = [
        r.id for r in catalog.roles.values() if r.authority is RoleAuthority.DECIDES
    ]
    assert deciders == ["project_board"]
    assert catalog.role("project_board").kind is RoleKind.HUMAN
    governance = {
        r.id
        for r in catalog.roles.values()
        if r.layer is RoleLayer.GOVERNANCE and r.kind is RoleKind.AGENT
    }
    assert governance == {
        "product_owner",
        "system_architect",
        "project_manager",
        "quality_manager",
        "release_manager",
    }
    for role_id in governance:
        spec = catalog.role(role_id)
        assert spec.authority is RoleAuthority.RECOMMENDS and spec.owns
        assert "project_board" in spec.controlled_by
    # The product owner owns the kravspec and controls what the analyst writes;
    # the system architect controls architecture, contracts and the task split.
    assert catalog.controls("product_owner", "requirements_analyst")
    for controlled in ("architect", "contract_author", "task_producer"):
        assert catalog.controls("system_architect", controlled)
    assert catalog.role("statistics").kind is RoleKind.SYSTEM


def test_tests_and_security_come_from_another_producer_than_the_coder() -> None:
    catalog = default_catalog()
    coder = _assign("j1", "coder", "anthropic", "s1")
    for role in ("test_designer", "security_reviewer"):
        with pytest.raises(RoleProcessError, match="producer"):
            validate_assignment(
                catalog, _assign("j2", role, "anthropic", "s2"), [coder]
            )
        validate_assignment(catalog, _assign("j2", role, "openai", "s2"), [coder])


def test_every_pipeline_task_type_has_a_role() -> None:
    catalog = default_catalog()
    task_types = {
        spec["task_type"] for spec in PipelineTaskMapping.STATE_TO_TASK.values()
    }
    for task_type in task_types:
        catalog.role_for_task_type(task_type)
    with pytest.raises(RoleProcessError):
        catalog.role_for_task_type("invented_task_type")


@pytest.mark.parametrize(
    "mutate, message",
    [
        (lambda d: d.update(independence_level="provider"), "independence_level"),
        (lambda d: d["roles"].append(dict(d["roles"][0])), "duplicate role"),
        (
            lambda d: next(r for r in d["roles"] if r["id"] == "coder").update(
                controlled_by=["code_auditor"]
            ),
            "fact_check",
        ),
        (
            lambda d: next(r for r in d["roles"] if r["id"] == "code_auditor").update(
                controlled_by=[]
            ),
            "no controlling role",
        ),
        (
            lambda d: next(r for r in d["roles"] if r["id"] == "coder").update(
                controlled_by=["fact_check", "coder"]
            ),
            "control itself",
        ),
        (
            lambda d: d["pipeline_task_roles"].update(generate_code="ghost"),
            "unknown role",
        ),
        # Decision 40: only a human decides; governance agents recommend.
        (
            lambda d: _role(d, "product_owner").update(authority="decides"),
            "authority decides",
        ),
        (
            lambda d: _role(d, "project_board").update(
                authority="recommends", kind="agent", controlled_by=["fact_check"]
            ),
            "no deciding",
        ),
        (
            lambda d: _role(d, "project_manager").update(controlled_by=["fact_check"]),
            "controlled by a deciding role",
        ),
        (lambda d: _role(d, "system_architect").pop("owns"), "must own"),
        (
            lambda d: _role(d, "task_producer").update(
                controlled_by=["fact_check", "project_board"]
            ),
            "challenges it",
        ),
        (lambda d: _role(d, "coder").update(layer="control"), "authority produces"),
        (lambda d: _role(d, "coder").pop("authority"), "invalid role entry"),
    ],
)
def test_inconsistent_catalog_fails_closed(mutate, message) -> None:
    data = copy.deepcopy(_raw())
    mutate(data)
    with pytest.raises(RoleProcessError, match=message):
        parse_catalog(data)


# --------------------------------------------------------------------- #
# Assignment rule
# --------------------------------------------------------------------- #
def test_any_agent_may_hold_any_role_across_packages() -> None:
    catalog = default_catalog()
    coder_on_a = _assign("j1", "coder", "anthropic", "s1", package="wp-a")
    # The same producer audits a different package: allowed.
    auditor_on_b = _assign("j2", "code_auditor", "anthropic", "s2", package="wp-b")
    validate_assignment(catalog, auditor_on_b, [coder_on_a])


def test_control_role_from_same_producer_is_rejected() -> None:
    catalog = default_catalog()
    coder = _assign("j1", "coder", "anthropic", "s1")
    with pytest.raises(RoleProcessError, match="different producers"):
        validate_assignment(
            catalog, _assign("j2", "code_auditor", "Anthropic", "s2"), [coder]
        )
    validate_assignment(catalog, _assign("j2", "code_auditor", "openai", "s2"), [coder])


def test_control_role_in_the_controlled_session_is_rejected() -> None:
    catalog = default_catalog()
    coder = _assign("j1", "coder", "anthropic", "s1")
    with pytest.raises(RoleProcessError, match="session"):
        validate_assignment(
            catalog, _assign("j2", "context_controller", "openai", "s1"), [coder]
        )


def test_rule_applies_in_both_directions() -> None:
    catalog = default_catalog()
    auditor = _assign("j2", "code_auditor", "openai", "s2")
    with pytest.raises(RoleProcessError, match="different producers"):
        validate_assignment(catalog, _assign("j1", "coder", "openai", "s1"), [auditor])


def test_unknown_producer_or_session_fails_closed() -> None:
    catalog = default_catalog()
    with pytest.raises(RoleProcessError, match="producer"):
        validate_assignment(catalog, _assign("j2", "code_auditor", None, "s2"), [])
    coder_without_brand = _assign("j1", "coder", None, None)
    with pytest.raises(RoleProcessError, match="cannot be verified"):
        validate_assignment(
            catalog,
            _assign("j2", "code_auditor", "openai", "s2"),
            [coder_without_brand],
        )


def test_roles_that_do_not_control_each_other_are_independent() -> None:
    catalog = default_catalog()
    auditor = _assign("j2", "code_auditor", "openai", "s2")
    # Two control roles from the same producer on one package are allowed.
    validate_assignment(
        catalog, _assign("j3", "context_controller", "openai", "s3"), [auditor]
    )


# --------------------------------------------------------------------- #
# Enforcement in the pipeline
# --------------------------------------------------------------------- #
YAML_SPEC = """
project_name: Demo
project_description: Demo
version: "1"
requirements:
  - id: R1
    description: Something
    acceptance_criteria: ["GET /health returns 200"]
"""


class _Runtime:
    def get_workflow(self, *args):
        return None


def _code_and_audit_tasks(orch: PipelineOrchestrator):
    """A coder job and a code-auditor job on the same work package."""
    from domain.task import Task, TaskStatus

    wid = orch.start_pipeline(YAML_SPEC, "org-1", "owner")
    workflow = orch._workflows[wid]
    code = Task(id="task-code", name="generate_code", workflow_id=wid)
    code.metadata = {"task_type": "generate_code", "organization_id": "org-1"}
    code.status = TaskStatus.PENDING
    orch._register_task(workflow, code)
    audit = Task(id="task-audit", name="audit", workflow_id=wid)
    # A control job carries the id of the package it controls.
    audit.metadata = {
        "task_type": "audit_code",
        "work_package_id": code.id,
        "organization_id": "org-1",
    }
    audit.status = TaskStatus.PENDING
    orch._register_task(workflow, audit)
    return wid, code, audit


def test_job_roles_come_from_the_catalog() -> None:
    orch = PipelineOrchestrator(_Runtime())
    _, code, _ = _code_and_audit_tasks(orch)
    assert orch._current_job(code.id).role == "coder"
    assert orch._current_job("task-audit").role == "code_auditor"


def test_pipeline_rejects_auditor_from_the_coders_producer() -> None:
    orch = PipelineOrchestrator(_Runtime())
    _, code, audit = _code_and_audit_tasks(orch)
    orch.bind_job_agent(
        code.id,
        AgentIdentity(tool="claude-code", brand="anthropic", session_id="s-code"),
    )
    with pytest.raises(RoleProcessError, match="different producers"):
        orch.bind_job_agent(
            audit.id,
            AgentIdentity(tool="claude-code", brand="anthropic", session_id="s-audit"),
        )
    assert orch._current_job(audit.id).agent.brand is None

    bound = orch.bind_job_agent(
        audit.id, AgentIdentity(tool="codex", brand="openai", session_id="s-audit")
    )
    assert bound.agent.brand == "openai"
    assert bound.work_package_id == code.id


def test_pipeline_rejects_agent_without_known_producer() -> None:
    orch = PipelineOrchestrator(_Runtime())
    _, code, _ = _code_and_audit_tasks(orch)
    with pytest.raises(RoleProcessError, match="producer"):
        orch.bind_job_agent(code.id, AgentIdentity(tool="claude-code"))


def test_plan_role_table_matches_the_catalog() -> None:
    """The plan shows the catalog; the catalog is the source. Keep them in step."""
    from pathlib import Path

    plan = (
        Path(__file__).resolve().parents[2]
        / "docs"
        / "plan"
        / "FAERDIGGOERELSESPLAN.md"
    ).read_text(encoding="utf-8")
    section = plan[plan.index("### Roller og kontekst") :]
    section = section[: section.index("\n### ", 4)]
    rows = {
        line.split("|")[1].strip()
        for line in section.splitlines()
        if line.startswith("| ")
        and not line.startswith("| Rolle")
        and "---" not in line
    }
    assert rows == {spec.name for spec in default_catalog().roles.values()}
