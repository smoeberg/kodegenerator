from __future__ import annotations

import json
from pathlib import Path

import pytest
from cryptography.fernet import Fernet

from services.runtime_configuration import validate_runtime_configuration
from services.runtime_secrets import RuntimeSecretError, materialize_runtime_secrets


def _secret(tmp_path: Path, name: str, value: str) -> str:
    path = tmp_path / name
    path.write_text(value, encoding="utf-8")
    return str(path)


def test_production_materializes_file_backed_secret(tmp_path: Path) -> None:
    secret = "authority-secret-value"
    environment = {
        "DOR_ENV": "production",
        "DOR_AUTHORITY_SIGNING_KEY_FILE": _secret(tmp_path, "authority", secret),
    }

    materialize_runtime_secrets(environment)

    assert environment["DOR_AUTHORITY_SIGNING_KEY"] == secret


def test_production_rejects_direct_secret_without_disclosure() -> None:
    secret = "direct-secret-must-not-be-accepted"
    environment = {
        "DOR_ENV": "production",
        "DOR_AUTHORITY_SIGNING_KEY": secret,
    }

    with pytest.raises(RuntimeSecretError) as error:
        materialize_runtime_secrets(environment)

    assert "DOR_AUTHORITY_SIGNING_KEY_FILE" in str(error.value)
    assert secret not in str(error.value)


def test_secret_cannot_have_direct_and_file_sources(tmp_path: Path) -> None:
    environment = {
        "DOR_ENV": "production",
        "DOR_WORKER_CREDENTIAL": "direct-value",
        "DOR_WORKER_CREDENTIAL_FILE": _secret(tmp_path, "worker", "file-value"),
    }

    with pytest.raises(RuntimeSecretError, match="may not both be set"):
        materialize_runtime_secrets(environment)


def test_development_keeps_direct_environment_compatibility() -> None:
    environment = {
        "DOR_ENV": "development",
        "DOR_ADMIN_PASSWORD": "development-only-value",
    }

    materialize_runtime_secrets(environment)

    assert environment["DOR_ADMIN_PASSWORD"] == "development-only-value"


def test_relative_secret_file_is_rejected() -> None:
    environment = {
        "DOR_ENV": "production",
        "DOR_ENCRYPTION_KEY_FILE": "relative/secret",
    }

    with pytest.raises(RuntimeSecretError, match="absolute path"):
        materialize_runtime_secrets(environment)


def test_symlink_secret_file_is_rejected(tmp_path: Path) -> None:
    target = tmp_path / "target"
    target.write_text("secret", encoding="utf-8")
    link = tmp_path / "link"
    link.symlink_to(target)
    environment = {
        "DOR_ENV": "production",
        "DOR_ENCRYPTION_KEY_FILE": str(link),
    }

    with pytest.raises(RuntimeSecretError, match="cannot be read"):
        materialize_runtime_secrets(environment)


def test_database_urls_are_derived_after_password_materialization(tmp_path: Path) -> None:
    environment = {
        "DOR_ENV": "production",
        "POSTGRES_DB": "dor",
        "POSTGRES_USER": "dor-user",
        "POSTGRES_HOST": "postgres",
        "POSTGRES_PASSWORD_FILE": _secret(tmp_path, "postgres", "p@ss:word\n"),
    }

    materialize_runtime_secrets(environment)

    expected = "postgresql+psycopg://dor-user:p%40ss%3Aword@postgres:5432/dor"
    assert environment["DATABASE_URL"] == expected
    assert environment["DOR_IDENTITY_DATABASE_URL"] == expected
    assert environment["DOR_PIPELINE_DATABASE_URL"] == expected


def test_secret_error_never_contains_file_payload(tmp_path: Path) -> None:
    secret = "payload-that-must-never-be-logged"
    path = tmp_path / "too-large"
    path.write_text(secret * 10_000, encoding="utf-8")
    environment = {
        "DOR_ENV": "production",
        "DOR_ADMIN_PASSWORD_FILE": str(path),
    }

    with pytest.raises(RuntimeSecretError) as error:
        materialize_runtime_secrets(environment)

    assert secret not in str(error.value)


def test_file_backed_api_configuration_passes_hardened_validation(
    tmp_path: Path,
) -> None:
    environment = {
        "ARTIFACT_BUCKET": "dor-artifacts",
        "ARTIFACT_STORE_URL": "http://minio:9000",
        "AWS_ACCESS_KEY_ID_FILE": _secret(tmp_path, "minio-user", "minio-user"),
        "AWS_SECRET_ACCESS_KEY_FILE": _secret(tmp_path, "minio-secret", "s" * 32),
        "DOR_ADMIN_ORGANIZATION_ID": "org-1",
        "DOR_ADMIN_PASSWORD_FILE": _secret(tmp_path, "admin", "a" * 32),
        "DOR_ADMIN_USERNAME": "admin",
        "DOR_AUTHORITY_SIGNING_KEY_FILE": _secret(tmp_path, "authority", "h" * 32),
        "DOR_ENCRYPTION_KEY_FILE": _secret(
            tmp_path, "encryption", Fernet.generate_key().decode("ascii")
        ),
        "DOR_ENV": "production",
        "DOR_JWT_ACTIVE_KEY_ID": "key-1",
        "DOR_JWT_SIGNING_KEYS_FILE": _secret(
            tmp_path, "jwt", json.dumps({"key-1": "j" * 32})
        ),
        "DOR_PIPELINE_STATE_ORGANIZATION_ID": "org-1",
        "DOR_QUEUE_BACKEND": "database",
        "DOR_RUNTIME_ROLE": "api",
        "POSTGRES_DB": "dor",
        "POSTGRES_HOST": "postgres",
        "POSTGRES_PASSWORD_FILE": _secret(tmp_path, "postgres", "p" * 32),
        "POSTGRES_USER": "dor",
    }

    materialize_runtime_secrets(environment)
    validate_runtime_configuration(environment)
