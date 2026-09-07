from pathlib import Path


def test_canonical_compose_uses_file_backed_production_secrets() -> None:
    compose = Path("compose.yml").read_text(encoding="utf-8")

    forbidden_direct_interpolation = (
        "POSTGRES_PASSWORD: ${POSTGRES_PASSWORD",
        "MINIO_ROOT_USER: ${MINIO_ROOT_USER",
        "MINIO_ROOT_PASSWORD: ${MINIO_ROOT_PASSWORD",
        "AWS_ACCESS_KEY_ID: ${",
        "AWS_SECRET_ACCESS_KEY: ${",
        "DOR_JWT_SIGNING_KEYS: ${",
        "DOR_JWT_SECRET_KEY: ${",
        "DOR_AUTHORITY_SIGNING_KEY: ${",
        "DOR_ENCRYPTION_KEY: ${",
        "DOR_ADMIN_PASSWORD: ${",
        "DOR_WORKER_CREDENTIAL: ${",
        "REDMINE_API_KEY: ${",
    )
    assert not any(token in compose for token in forbidden_direct_interpolation)

    required_file_inputs = (
        "POSTGRES_PASSWORD_FILE: /run/secrets/postgres_password",
        "MINIO_ROOT_USER_FILE: /run/secrets/minio_root_user",
        "MINIO_ROOT_PASSWORD_FILE: /run/secrets/minio_root_password",
        "AWS_ACCESS_KEY_ID_FILE: /run/secrets/minio_root_user",
        "AWS_SECRET_ACCESS_KEY_FILE: /run/secrets/minio_root_password",
        "DOR_JWT_SIGNING_KEYS_FILE: /run/secrets/dor_jwt_signing_keys",
        "DOR_AUTHORITY_SIGNING_KEY_FILE: /run/secrets/dor_authority_signing_key",
        "DOR_ENCRYPTION_KEY_FILE: /run/secrets/dor_encryption_key",
        "DOR_ADMIN_PASSWORD_FILE: /run/secrets/dor_admin_password",
        "DOR_WORKER_CREDENTIAL_FILE: /run/secrets/dor_worker_credential",
    )
    assert all(token in compose for token in required_file_inputs)


def test_env_example_contains_secret_paths_not_secret_values() -> None:
    example = Path(".env.example").read_text(encoding="utf-8")

    forbidden_assignments = (
        "POSTGRES_PASSWORD=",
        "MINIO_ROOT_USER=",
        "MINIO_ROOT_PASSWORD=",
        "AWS_ACCESS_KEY_ID=",
        "AWS_SECRET_ACCESS_KEY=",
        "DOR_JWT_SIGNING_KEYS=",
        "DOR_JWT_SECRET_KEY=",
        "DOR_AUTHORITY_SIGNING_KEY=",
        "DOR_ENCRYPTION_KEY=",
        "DOR_ADMIN_PASSWORD=",
        "DOR_WORKER_CREDENTIAL=",
        "OPENAI_API_KEY=",
        "REDMINE_API_KEY=",
    )
    lines = tuple(line.strip() for line in example.splitlines())
    assert not any(
        line.startswith(prefix)
        for line in lines
        for prefix in forbidden_assignments
    )
    assert "DOR_SECRET_POSTGRES_PASSWORD_FILE=" in example
    assert "DOR_SECRET_JWT_SIGNING_KEYS_FILE=" in example
    assert "DOR_SECRET_AUTHORITY_SIGNING_KEY_FILE=" in example


def test_container_entrypoint_delegates_to_secret_aware_runtime() -> None:
    entrypoint = Path("scripts/entrypoint.sh").read_text(encoding="utf-8")

    assert 'exec python -m scripts.runtime_entrypoint "$@"' in entrypoint
