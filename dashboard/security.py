"""Fail-closed secret handling for the DOR dashboard."""

from __future__ import annotations

import os

from cryptography.fernet import Fernet, InvalidToken


class DashboardConfigurationError(RuntimeError):
    """Required dashboard security configuration is absent or invalid."""


class DashboardSecretError(RuntimeError):
    """Encrypted dashboard data cannot be safely decrypted."""


def _required_environment_value(name: str) -> str:
    value = os.getenv(name)
    if value is None or not value.strip():
        raise DashboardConfigurationError(f"{name} must be configured")
    return value


def admin_password() -> str:
    """Return the explicitly configured dashboard administrator password."""
    return _required_environment_value("DOR_ADMIN_PASSWORD")


def _fernet() -> Fernet:
    raw_key = _required_environment_value("DOR_ENCRYPTION_KEY")
    try:
        return Fernet(raw_key.encode("ascii"))
    except (UnicodeEncodeError, ValueError) as exc:
        raise DashboardConfigurationError(
            "DOR_ENCRYPTION_KEY must be a valid Fernet key"
        ) from exc


def encrypt_secret(plain_text: str) -> str:
    """Encrypt a non-empty secret; encryption failures are never downgraded."""
    if not plain_text:
        return ""
    return _fernet().encrypt(plain_text.encode("utf-8")).decode("ascii")


def decrypt_secret(cipher_text: str) -> str:
    """Decrypt a secret or fail closed when ciphertext integrity is invalid."""
    if not cipher_text:
        return ""
    try:
        return _fernet().decrypt(cipher_text.encode("ascii")).decode("utf-8")
    except (InvalidToken, UnicodeDecodeError, UnicodeEncodeError) as exc:
        raise DashboardSecretError(
            "Stored dashboard secret failed integrity validation"
        ) from exc
