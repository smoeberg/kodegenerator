"""File-backed secret materialization for hardened DOR runtimes.

Production deployments provide secret *paths* to the container. Secret values
are read only after process start and are never required in Compose
interpolation or image metadata. Development and demo keep their existing
direct-environment compatibility.
"""

from __future__ import annotations

import os
import stat
from collections.abc import MutableMapping
from pathlib import Path
from urllib.parse import quote

MAX_SECRET_BYTES = 64 * 1024

FILE_BACKED_SECRET_NAMES = frozenset(
    {
        "AWS_ACCESS_KEY_ID",
        "AWS_SECRET_ACCESS_KEY",
        "DATABASE_URL",
        "DOR_ADMIN_PASSWORD",
        "DOR_AUTHORITY_SIGNING_KEY",
        "DOR_ENCRYPTION_KEY",
        "DOR_IDENTITY_DATABASE_URL",
        "DOR_JWT_SECRET_KEY",
        "DOR_JWT_SIGNING_KEYS",
        "DOR_PIPELINE_DATABASE_URL",
        "DOR_WORKER_CREDENTIAL",
        "OPENAI_API_KEY",
        "POSTGRES_PASSWORD",
        "REDMINE_API_KEY",
    }
)

_DATABASE_URL_NAMES = (
    "DATABASE_URL",
    "DOR_IDENTITY_DATABASE_URL",
    "DOR_PIPELINE_DATABASE_URL",
)


class RuntimeSecretError(RuntimeError):
    """Production secret input is missing, ambiguous, or unsafe."""


def materialize_runtime_secrets(
    environment: MutableMapping[str, str] | None = None,
) -> None:
    """Resolve allowlisted ``*_FILE`` inputs into the current process environment.

    In production, a secret may not arrive directly in the inherited process
    environment. This prevents canonical Compose interpolation from becoming a
    secret transport. A secret file is bounded, regular, non-symlinked and
    UTF-8 text. Values are never included in raised errors.
    """

    values = os.environ if environment is None else environment
    production = values.get("DOR_ENV", "development").strip().lower() == "production"

    for name in sorted(FILE_BACKED_SECRET_NAMES):
        direct = values.get(name, "")
        file_name = f"{name}_FILE"
        file_value = values.get(file_name, "").strip()

        if direct and file_value:
            raise RuntimeSecretError(f"{name} and {file_name} may not both be set")
        if production and direct:
            raise RuntimeSecretError(
                f"{name} must be provided through {file_name} in production"
            )
        if file_value:
            values[name] = _read_secret_file(file_name, file_value)

    if production:
        _derive_database_urls(values)


def _read_secret_file(name: str, raw_path: str) -> str:
    path = Path(raw_path)
    if not path.is_absolute():
        raise RuntimeSecretError(f"{name} must reference an absolute path")

    flags = os.O_RDONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise RuntimeSecretError(f"{name} cannot be read") from exc

    try:
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode):
            raise RuntimeSecretError(f"{name} must reference a regular file")
        if metadata.st_size < 1 or metadata.st_size > MAX_SECRET_BYTES:
            raise RuntimeSecretError(
                f"{name} must contain between 1 and {MAX_SECRET_BYTES} bytes"
            )
        with os.fdopen(os.dup(descriptor), "rb") as handle:
            payload = handle.read(MAX_SECRET_BYTES + 1)
    except OSError as exc:
        raise RuntimeSecretError(f"{name} cannot be read") from exc
    finally:
        os.close(descriptor)

    if len(payload) > MAX_SECRET_BYTES:
        raise RuntimeSecretError(f"{name} exceeds the maximum secret size")
    try:
        value = payload.decode("utf-8").rstrip("\r\n")
    except UnicodeDecodeError as exc:
        raise RuntimeSecretError(f"{name} cannot be read as UTF-8 text") from exc
    if not value:
        raise RuntimeSecretError(f"{name} must not be empty")
    return value


def _derive_database_urls(values: MutableMapping[str, str]) -> None:
    """Build the canonical SQLAlchemy URL after the password file is materialized."""

    if any(values.get(name, "").strip() for name in _DATABASE_URL_NAMES):
        return
    required = ("POSTGRES_DB", "POSTGRES_USER", "POSTGRES_PASSWORD")
    missing = [name for name in required if not values.get(name, "").strip()]
    if missing:
        return

    user = quote(values["POSTGRES_USER"].strip(), safe="")
    password = quote(values["POSTGRES_PASSWORD"], safe="")
    database = quote(values["POSTGRES_DB"].strip(), safe="")
    host = values.get("POSTGRES_HOST", "postgres").strip() or "postgres"
    port = values.get("POSTGRES_PORT", "5432").strip() or "5432"
    url = f"postgresql+psycopg://{user}:{password}@{host}:{port}/{database}"
    for name in _DATABASE_URL_NAMES:
        values[name] = url
