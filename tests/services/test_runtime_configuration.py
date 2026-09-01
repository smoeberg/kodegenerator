import json

import pytest
from cryptography.fernet import Fernet

from services.runtime_configuration import (
    RuntimeConfigurationError,
    validate_runtime_configuration,
)


def _environment(role: str) -> dict[str, str]:
    database = "postgresql+psycopg://dor:secret@postgres:5432/dor"
    values = {
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
        "DOR_RUNTIME_ROLE": role,
        "DOR_WORKER_CAPABILITIES": "pipeline.code,pipeline.tests",
        "DOR_WORKER_CREDENTIAL": "w" * 32,
        "DOR_WORKER_ORGANIZATION_ID": "org-1",
        "DOR_WORKER_SERVICE_ID": "factory-worker",
    }
    return values


@pytest.mark.parametrize("role", ["api", "dashboard", "migrate", "worker"])
def test_hardened_runtime_roles_accept_canonical_wiring(role: str) -> None:
    validate_runtime_configuration(_environment(role))


def test_development_environment_does_not_require_demo_wiring() -> None:
    validate_runtime_configuration({"DOR_ENV": "development"})


@pytest.mark.parametrize(
    ("name", "value", "message"),
    [
        ("DATABASE_URL", "sqlite:///demo.db", "PostgreSQL"),
        ("DOR_QUEUE_BACKEND", "sqlite", "database"),
        ("DOR_AUTHORITY_SIGNING_KEY", "short", "32 characters"),
        ("DOR_ENCRYPTION_KEY", "not-fernet", "Fernet"),
    ],
)
def test_hardened_runtime_rejects_unsafe_values(
    name: str, value: str, message: str
) -> None:
    environment = _environment("api")
    environment[name] = value

    with pytest.raises(RuntimeConfigurationError, match=message):
        validate_runtime_configuration(environment)


def test_hardened_runtime_rejects_divergent_database_wiring() -> None:
    environment = _environment("worker")
    environment["DOR_PIPELINE_DATABASE_URL"] = (
        "postgresql+psycopg://dor:secret@other:5432/dor"
    )

    with pytest.raises(RuntimeConfigurationError, match="share DATABASE_URL"):
        validate_runtime_configuration(environment)


def test_placeholder_failure_does_not_disclose_secret() -> None:
    environment = _environment("worker")
    secret = "generated-worker-secret-value"
    environment["DOR_WORKER_CREDENTIAL"] = secret

    with pytest.raises(RuntimeConfigurationError) as error:
        validate_runtime_configuration(environment)

    assert "DOR_WORKER_CREDENTIAL" in str(error.value)
    assert secret not in str(error.value)
