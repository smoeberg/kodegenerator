from phase5.p5_00_ai_work_product_contract import (
    AIWorkProductContract,
    AcceptanceCriterion,
    ArtifactRequirement,
    ArtifactType,
    VerificationProcedure,
)


def make_contract():
    return AIWorkProductContract(
        contract_id="P5-00",
        contract_version="1.0.0",
        product_type="ai-work-product",
        product_location="phase5/p5-00-ai-work-product-contract",
        intent="Define and verify DOR work products",
        inputs=("architecture",),
        required_artifacts=(ArtifactRequirement("domain", ArtifactType.FILE, "models.py"),),
        outputs=("verified-work-product",),
        acceptance_criteria=(AcceptanceCriterion(
            "P5-00-AC-001", "contract immutable", "contract_immutable", "p3-20", "governed_test_execution"
        ),),
        verification_procedure=VerificationProcedure("P3-20", "p3-20", "criterion-by-criterion", "1"),
        regression_requirements=("full-suite",),
        required_capabilities=("repository-write",),
        authority_boundaries=("agent-cannot-verify",),
        forbidden_actions=("self-approve",),
        forbidden_outputs=("agent-pass",),
    )


def test_contract_has_stable_fingerprint():
    assert make_contract().contract_fingerprint == make_contract().contract_fingerprint


def test_contract_fingerprint_changes_when_requirement_changes():
    first = make_contract()
    changed = AIWorkProductContract(
        contract_id=first.contract_id,
        contract_version=first.contract_version,
        product_type=first.product_type,
        product_location=first.product_location,
        intent="changed",
        inputs=first.inputs,
        required_artifacts=first.required_artifacts,
        outputs=first.outputs,
        acceptance_criteria=first.acceptance_criteria,
        verification_procedure=first.verification_procedure,
        regression_requirements=first.regression_requirements,
        required_capabilities=first.required_capabilities,
        authority_boundaries=first.authority_boundaries,
        forbidden_actions=first.forbidden_actions,
        forbidden_outputs=first.forbidden_outputs,
    )
    assert first.contract_fingerprint != changed.contract_fingerprint


def test_contract_requires_p3_20():
    try:
        AIWorkProductContract(
            contract_id="x", contract_version="1", product_type="x", product_location="x", intent="x",
            inputs=(), required_artifacts=(ArtifactRequirement("a", ArtifactType.FILE, "a"),), outputs=(),
            acceptance_criteria=(), verification_procedure=VerificationProcedure("x", "agent", "x", "1"),
            regression_requirements=(), required_capabilities=(), authority_boundaries=(),
            forbidden_actions=(), forbidden_outputs=(),
        )
    except ValueError as exc:
        assert "p3-20" in str(exc)
    else:
        raise AssertionError("non-P3-20 verifier must be rejected")
