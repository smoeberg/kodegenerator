import hashlib

import pytest

from phase4.council.configuration import (
    AllocationMember,
    AutonomyLevel,
    CouncilTemplate,
    IndependenceLevel,
    ProtocolFunction,
    RoleAllocationPool,
    TemplateStage,
)
from phase4.verification.allocation_selector import (
    CouncilSelectionError,
    DeterministicCouncilSelector,
    SelectionCandidate,
    SelectionRequestContext,
)


def candidate(profile: str, rank: int, *, connection: str, brand: str = "brand"):
    digest = hashlib.sha256(profile.encode()).hexdigest()
    return SelectionCandidate(
        bot_profile_id=profile,
        bot_profile_version=1,
        profile_fingerprint=digest,
        agent_identity=digest,
        deployment_id=f"deployment-{profile}",
        deployment_revision=1,
        deployment_fingerprint=digest,
        connection_id=connection,
        connection_version=1,
        connection_fingerprint=digest,
        provider="openai-compatible",
        brand=brand,
        model_family=f"family-{rank}",
        data_boundary="eu",
        region="eu-west",
        capabilities=("architecture.design",),
        enabled=True,
        deployment_status="active",
    )


def configured(independence=IndependenceLevel.CONNECTION):
    template = CouncilTemplate(
        template_id="architecture",
        organization_id="org-1",
        name="Architecture",
        stages=(
            TemplateStage(
                stage_id="review",
                protocol_function=ProtocolFunction.REVIEWER,
                role_versions=(("reviewer", 1),),
                minimum_assignments=2,
                maximum_assignments=2,
                parallel=True,
            ),
        ),
        approved_by="owner",
    )
    allocation = RoleAllocationPool(
        allocation_id="reviewers",
        organization_id="org-1",
        role_id="reviewer",
        role_version=1,
        members=(
            AllocationMember("bot-a", 1, 1),
            AllocationMember("bot-b", 1, 2),
            AllocationMember("bot-c", 1, 3),
        ),
        independence_level=independence,
        autonomy_level=AutonomyLevel.HUMAN_APPROVES,
        hard_constraints=(("data_boundary", "eu"),),
        approved_by="owner",
    )
    return template, allocation


def selection_context(template, *, base_sha="1" * 40):
    return SelectionRequestContext(
        organization_id="org-1",
        scope_id="session-1",
        repository="smoeberg/kodegenerator",
        base_sha=base_sha,
        requirements_fingerprint="2" * 64,
        architecture_fingerprint="3" * 64,
        contract_fingerprint="4" * 64,
        input_fingerprint="5" * 64,
        template_fingerprint=template.fingerprint,
    )


def test_selection_is_deterministic_and_records_rejections() -> None:
    template, allocation = configured()
    candidates = {
        ("bot-a", 1): candidate("bot-a", 1, connection="shared"),
        ("bot-b", 1): candidate("bot-b", 2, connection="shared"),
        ("bot-c", 1): candidate("bot-c", 3, connection="other"),
    }
    arguments = dict(
        run_id="run-1",
        organization_id="org-1",
        template=template,
        allocations={("reviewer", 1): allocation},
        candidates=candidates,
        context=selection_context(template),
    )
    first = DeterministicCouncilSelector().select(**arguments)
    second = DeterministicCouncilSelector().select(**arguments)
    assert first.assignments == second.assignments
    assert [a.bot_profile_id for a in first.assignments] == ["bot-a", "bot-c"]
    assert [r.reason for r in first.receipts] == [
        "selected",
        "independence:connection",
        "selected",
    ]
    assert first.fingerprint == second.fingerprint
    other_run = DeterministicCouncilSelector().select(
        **{**arguments, "run_id": "run-2"}
    )
    assert other_run.fingerprint == first.fingerprint
    assert other_run.assignments == first.assignments


def test_selection_fails_closed_when_minimum_cannot_be_met() -> None:
    template, allocation = configured(IndependenceLevel.BRAND)
    candidates = {
        ("bot-a", 1): candidate("bot-a", 1, connection="a"),
        ("bot-b", 1): candidate("bot-b", 2, connection="b"),
        ("bot-c", 1): candidate("bot-c", 3, connection="c"),
    }
    result = DeterministicCouncilSelector().select(
        run_id="run-1",
        organization_id="org-1",
        template=template,
        allocations={("reviewer", 1): allocation},
        candidates=candidates,
        context=selection_context(template),
    )
    assert result.status == "blocked"
    assert result.assignments == ()
    assert "only 1" in result.rationale


def test_unknown_hard_constraint_is_rejected_not_ignored() -> None:
    template, allocation = configured()
    allocation = RoleAllocationPool(
        **{
            **allocation.__dict__,
            "hard_constraints": (("unknown_policy", True),),
        }
    )
    with pytest.raises(CouncilSelectionError, match="unsupported"):
        DeterministicCouncilSelector().select(
            run_id="run-1",
            organization_id="org-1",
            template=template,
            allocations={("reviewer", 1): allocation},
            candidates={
                ("bot-a", 1): candidate("bot-a", 1, connection="connection")
            },
            context=selection_context(template),
        )


def test_candidates_after_capacity_receive_an_explicit_receipt() -> None:
    template, allocation = configured(IndependenceLevel.PROFILE)
    template = CouncilTemplate(
        template_id=template.template_id,
        organization_id=template.organization_id,
        name=template.name,
        stages=(
            TemplateStage(
                stage_id="review",
                protocol_function=ProtocolFunction.REVIEWER,
                role_versions=(("reviewer", 1),),
                maximum_assignments=1,
            ),
        ),
        approved_by=template.approved_by,
    )
    candidates = {
        (name, 1): candidate(name, index, connection=name)
        for index, name in enumerate(("bot-a", "bot-b", "bot-c"), start=1)
    }
    result = DeterministicCouncilSelector().select(
        run_id="run-1",
        organization_id="org-1",
        template=template,
        allocations={("reviewer", 1): allocation},
        candidates=candidates,
        context=selection_context(template),
    )
    assert [receipt.reason for receipt in result.receipts] == [
        "selected",
        "stage_capacity_reached",
        "stage_capacity_reached",
    ]


def test_request_context_binds_repository_base_and_all_input_fingerprints() -> None:
    context = SelectionRequestContext(
        organization_id="org-1",
        scope_id="session-1",
        repository="smoeberg/kodegenerator",
        base_sha="a" * 40,
        requirements_fingerprint="b" * 64,
        architecture_fingerprint="c" * 64,
        contract_fingerprint="d" * 64,
        input_fingerprint="e" * 64,
        template_fingerprint="f" * 64,
    )
    changed = SelectionRequestContext(
        **{**context.__dict__, "base_sha": "1" * 40}
    )
    assert context.fingerprint != changed.fingerprint
