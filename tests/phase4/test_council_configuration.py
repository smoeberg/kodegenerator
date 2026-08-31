import pytest

from phase4.council.configuration import (
    AllocationMember,
    AutonomyLevel,
    CouncilRoleDefinition,
    CouncilTemplate,
    IndependenceLevel,
    ProtocolFunction,
    RoleAllocationPool,
    TemplateStage,
)


def role() -> CouncilRoleDefinition:
    return CouncilRoleDefinition(
        role_id="chief-architect",
        organization_id="org-1",
        name="Chief Architect",
        purpose="Own the architecture conversation",
        protocol_function=ProtocolFunction.PROPOSER,
        required_capabilities=("architecture.design",),
        output_schema_ref="architecture-v1",
        rubric_ref="architecture-rubric-v1",
    )


def test_role_and_template_are_provider_neutral_and_version_bound() -> None:
    value = role()
    stage = TemplateStage(
        stage_id="proposal",
        protocol_function=ProtocolFunction.PROPOSER,
        role_versions=((value.role_id, value.version),),
    )
    template = CouncilTemplate(
        template_id="architecture-council",
        organization_id="org-1",
        name="Architecture Council",
        stages=(stage,),
        approved_by="owner",
    )
    assert "claude" not in str(template).lower()
    assert stage.role_versions == (("chief-architect", 1),)
    assert len(template.fingerprint) == 64


def test_stage_bounds_and_role_versions_fail_closed() -> None:
    with pytest.raises(ValueError, match="bounds"):
        TemplateStage(
            stage_id="review",
            protocol_function=ProtocolFunction.REVIEWER,
            role_versions=(("reviewer", 1),),
            minimum_assignments=2,
            maximum_assignments=1,
        )


def test_allocation_preserves_explicit_preference_and_fallback() -> None:
    pool = RoleAllocationPool(
        allocation_id="architect-pool",
        organization_id="org-1",
        role_id="chief-architect",
        role_version=1,
        members=(
            AllocationMember("architect-1", 1, preference_rank=1),
            AllocationMember("architect-2", 3, preference_rank=2, fallback_rank=1),
        ),
        independence_level=IndependenceLevel.CONNECTION,
        autonomy_level=AutonomyLevel.HUMAN_APPROVES,
        approved_by="owner",
    )
    assert pool.members[1].fallback_rank == 1
    assert len(pool.fingerprint) == 64
