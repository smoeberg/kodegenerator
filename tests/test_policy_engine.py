# tests/test_policy_engine.py
import pytest
from domain.policy import Policy
from domain.artifact import Artifact, ArtifactType, ArtifactState, Signature
from runtime.policy_engine import PolicyEngine

@pytest.fixture
def no_direct_commits_policy():
    return Policy(
        id="no_direct_commits",
        name="No Direct Commits to Main",
        scope="global",
        conditions={
            "required_approvals": ["architecture_reviewer", "qa"],
            "min_consensus_score": 80
        },
        actions={
            "on_violation": "block"
        }
    )

@pytest.fixture
def sample_artifact():
    return Artifact(
        id="artifact_1",
        version="1.0.0",
        artifact_type=ArtifactType.IMPLEMENTATION,
        state=ArtifactState.SUBMITTED,
        signatures=[
            Signature(role_id="architecture_reviewer", actor_id="actor_1", status="approved"),
            Signature(role_id="qa", actor_id="actor_2", status="approved")
        ],
        consensus_score=90.0
    )

def test_check_compliance(no_direct_commits_policy, sample_artifact):
    engine = PolicyEngine([no_direct_commits_policy])
    assert engine.check_compliance(
        target="global",
        action="merge_to_main",
        artifact=sample_artifact
    )

def test_policy_violation(no_direct_commits_policy):
    artifact = Artifact(
        id="artifact_2",
        version="1.0.0",
        artifact_type=ArtifactType.IMPLEMENTATION,
        state=ArtifactState.SUBMITTED,
        signatures=[
            Signature(role_id="architecture_reviewer", actor_id="actor_1", status="approved")
            # Mangler QA godkendelse
        ],
        consensus_score=90.0
    )
    engine = PolicyEngine([no_direct_commits_policy])
    violations = engine.get_violations(
        target="global",
        action="merge_to_main",
        artifact=artifact
    )
    assert len(violations) == 1
    assert violations[0].id == "no_direct_commits"
