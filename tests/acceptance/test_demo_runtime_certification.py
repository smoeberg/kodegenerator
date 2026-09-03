"""Hermetic certification suite for the canonical Compose demo stack."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any
import pytest
from cryptography.fernet import Fernet

from alembic.config import Config
from alembic.script import ScriptDirectory
from domain.factory_integration import IntegrationStatus, ReleaseHandoff
from domain.factory_work import fingerprint
from phase4.authority.engine import AuthorityEngine
from phase4.authority.grants import VerifiedAuthorityGrant
from phase4.authority.models import (
    AuthorityPolicy,
    AuthorityRequest,
    AuthorityRule,
    Decision,
)
from services.delivery_evidence_gate import (
    AttestedDeliveryGate,
    DeliveryEvidenceError,
)
from services.runtime_configuration import (
    RuntimeConfigurationError,
    validate_runtime_configuration,
)


@pytest.fixture
def repo_root() -> Path:
    return Path(__file__).resolve().parent.parent.parent


def test_contract_and_manifest_declared_certified(repo_root: Path) -> None:
    manifest_path = repo_root / "ci" / "manifests" / "demo_installation_contract.json"
    assert manifest_path.exists(), "Manifest must exist"
    with manifest_path.open("r", encoding="utf-8") as f:
        manifest = json.load(f)
    assert manifest["schema_version"] == 1
    assert manifest["compose"]["project_name"] == "dor"


def test_alembic_head_matches_repository_contract(repo_root: Path) -> None:
    alembic_cfg = Config(str(repo_root / "alembic.ini"))
    script = ScriptDirectory.from_config(alembic_cfg)
    heads = script.get_heads()
    assert heads == ["025_swarm_control_state"]


def test_runtime_configuration_fail_closed_on_missing_or_drift() -> None:
    database = "postgresql+psycopg://dor:secret@postgres:5432/dor"
    valid_env = {
        "ARTIFACT_BUCKET": "dor-artifacts",
        "ARTIFACT_STORE_URL": "http://minio:9000",
        "AWS_ACCESS_KEY_ID": "minio-user",
        "AWS_SECRET_ACCESS_KEY": "s" * 32,
        "DATABASE_URL": database,
        "DOR_ADMIN_ORGANIZATION_ID": "org-1",
        "DOR_ADMIN_PASSWORD": "a" * 32,
        "DOR_ADMIN_USERNAME": "admin",
        "DOR_API_BASE": "http://api:8000",
        "DOR_AUTHORITY_SIGNING_KEY": "h" * 32,
        "DOR_ENCRYPTION_KEY": Fernet.generate_key().decode("ascii"),
        "DOR_ENV": "demo",
        "DOR_IDENTITY_DATABASE_URL": database,
        "DOR_JWT_ACTIVE_KEY_ID": "key-1",
        "DOR_JWT_SIGNING_KEYS": json.dumps({"key-1": "j" * 32}),
        "DOR_PIPELINE_DATABASE_URL": database,
        "DOR_PIPELINE_STATE_ORGANIZATION_ID": "org-1",
        "DOR_QUEUE_BACKEND": "database",
        "DOR_RUNTIME_ROLE": "api",
        "DOR_WORKER_CAPABILITIES": "pipeline.code,pipeline.tests",
        "DOR_WORKER_CREDENTIAL": "w" * 32,
        "DOR_WORKER_ORGANIZATION_ID": "org-1",
        "DOR_WORKER_SERVICE_ID": "factory-worker",
    }

    # Valid configuration passes
    validate_runtime_configuration(valid_env)

    # Insecure sqlite fails closed
    invalid_env = dict(valid_env)
    invalid_env["DATABASE_URL"] = "sqlite:///demo.db"
    with pytest.raises(RuntimeConfigurationError):
        validate_runtime_configuration(invalid_env)


def test_delivery_evidence_gate_tenant_and_attestation_fencing() -> None:
    class InMemoryStore:
        def __init__(self) -> None:
            self.plans: dict[tuple[str, str], Any] = {}
            self.receipts: dict[tuple[str, str], Any] = {}

        def get_plan(self, organization_id: str, plan_id: str) -> Any:
            return self.plans.get((organization_id, plan_id))

        def get_receipt_for_plan(self, organization_id: str, plan_fingerprint: str) -> Any:
            return self.receipts.get((organization_id, plan_fingerprint))

    store = InMemoryStore()
    gate = AttestedDeliveryGate(store)

    sha1_base = "a" * 40
    sha1_head = "b" * 40
    plan_fp = "1" * 64
    receipt_id = "2" * 64
    patch_content = "diff --git a/app.py b/app.py\n"
    patch_fp = fingerprint(patch_content)

    plan = SimpleNamespace(
        plan_id="plan-1",
        content_fingerprint=plan_fp,
        repository="owner/repo",
        base_sha=sha1_base,
        integration_branch="factory/integration/demo",
        status=IntegrationStatus.SUCCEEDED,
    )
    receipt = SimpleNamespace(
        receipt_id=receipt_id,
        plan_id="plan-1",
        integration_head_sha=sha1_head,
        integration_branch="factory/integration/demo",
        suite_attestation=(("failures", "0"), ("status", "passed"), ("tests_run", "3")),
        status=IntegrationStatus.SUCCEEDED,
    )

    store.plans[("org-1", "plan-1")] = plan
    store.receipts[("org-1", plan_fp)] = receipt

    handoff = ReleaseHandoff(
        organization_id="org-1",
        repository="owner/repo",
        branch="factory/integration/demo",
        base_sha=sha1_base,
        head_sha=sha1_head,
        plan_fingerprint=plan_fp,
        integration_receipt_id=receipt_id,
        test_attestation=(("failures", "0"), ("status", "passed"), ("tests_run", "3")),
        patch_fingerprint=patch_fp,
        patch_content=patch_content,
    )

    request_params = {
        "integration_receipt_id": receipt_id,
        "plan_fingerprint": plan_fp,
        "base_sha": sha1_base,
        "head_sha": sha1_head,
        "patch_fingerprint": patch_fp,
        "patch_id": patch_fp,
        "base_branch": "main",
    }

    request = AuthorityRequest.create(
        "release-controller",
        "release.publish",
        "repository:owner/repo",
        "release-context",
        organization_id="org-1",
        capability="release.publish",
        parameters=request_params,
    )
    policy = AuthorityPolicy(
        "release-policy",
        "1",
        (
            AuthorityRule(
                "allow-release",
                "release.publish",
                "repository:owner/repo",
                Decision.ALLOW,
                agent_identity="release-controller",
            ),
        ),
    )
    grant = VerifiedAuthorityGrant.from_decision(AuthorityEngine(policy).evaluate(request))

    bound = gate.bind({"organization_id": "org-1", "release_handoff": handoff}, grant, action="release.publish")
    assert bound["repository"] == "owner/repo"
    assert bound["patch_id"] == patch_fp

    # Cross-tenant breach rejection
    foreign_request = AuthorityRequest.create(
        "release-controller",
        "release.publish",
        "repository:owner/repo",
        "release-context",
        organization_id="org-2",
        capability="release.publish",
        parameters=request_params,
    )
    foreign_grant = VerifiedAuthorityGrant.from_decision(AuthorityEngine(policy).evaluate(foreign_request))
    with pytest.raises(DeliveryEvidenceError):
        gate.bind({"organization_id": "org-2", "release_handoff": handoff}, foreign_grant, action="release.publish")
