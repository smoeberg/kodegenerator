"""Fail-closed JWT signing-key selection, rotation, and revocation."""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass


_KEY_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
_LEGACY_KEY_ID = "legacy"


class JWTKeyConfigurationError(RuntimeError):
    """Raised when JWT signing-key configuration is unsafe or inconsistent."""


class JWTKeyRejectedError(ValueError):
    """Raised when a token references an unknown or revoked signing key."""


@dataclass(frozen=True)
class JWTKeyRing:
    """Immutable set of verification keys with exactly one active signer."""

    keys: dict[str, str]
    active_key_id: str
    revoked_key_ids: frozenset[str]

    @classmethod
    def from_environment(cls, *, production: bool | None = None) -> "JWTKeyRing":
        """Build a keyring from environment configuration.

        ``DOR_JWT_SIGNING_KEYS`` is a JSON object mapping key IDs to HMAC
        secrets. ``DOR_JWT_ACTIVE_KEY_ID`` selects the issuer key and
        ``DOR_JWT_REVOKED_KEY_IDS`` is a comma-separated denylist. If no JSON
        keyring is configured, the existing ``DOR_JWT_SECRET_KEY`` is exposed
        as the ``legacy`` key for a backwards-compatible migration path.
        """
        if production is None:
            production = os.getenv("DOR_ENV", "development").lower() == "production"

        serialized = os.getenv("DOR_JWT_SIGNING_KEYS", "").strip()
        if serialized:
            keys = _parse_keys(serialized)
            active_key_id = os.getenv("DOR_JWT_ACTIVE_KEY_ID", "").strip()
            if not active_key_id:
                raise JWTKeyConfigurationError(
                    "DOR_JWT_ACTIVE_KEY_ID is required when DOR_JWT_SIGNING_KEYS is set"
                )
        else:
            secret = os.getenv("DOR_JWT_SECRET_KEY", "").strip()
            if not secret and not production:
                secret = "dev-insecure-secret-key-32-chars-long-xxx"
            if not secret:
                raise JWTKeyConfigurationError(
                    "DOR_JWT_SECRET_KEY or DOR_JWT_SIGNING_KEYS must be configured"
                )
            keys = {_LEGACY_KEY_ID: secret}
            active_key_id = _LEGACY_KEY_ID

        _validate_key_id(active_key_id)
        if active_key_id not in keys:
            raise JWTKeyConfigurationError("active JWT key ID is not present in the keyring")

        revoked = frozenset(
            value.strip()
            for value in os.getenv("DOR_JWT_REVOKED_KEY_IDS", "").split(",")
            if value.strip()
        )
        for key_id in revoked:
            _validate_key_id(key_id)
        if active_key_id in revoked:
            raise JWTKeyConfigurationError("active JWT signing key cannot be revoked")
        if production:
            weak = sorted(key_id for key_id, secret in keys.items() if len(secret) < 32)
            if weak:
                raise JWTKeyConfigurationError(
                    "production JWT HMAC keys must contain at least 32 characters: "
                    + ", ".join(weak)
                )
        return cls(keys=keys, active_key_id=active_key_id, revoked_key_ids=revoked)

    @property
    def signing_key(self) -> str:
        return self.keys[self.active_key_id]

    def verification_key(self, key_id: object) -> str:
        """Resolve a token key ID without falling back to another key."""
        if not isinstance(key_id, str) or not key_id:
            raise JWTKeyRejectedError("JWT header has no signing key ID")
        if key_id in self.revoked_key_ids:
            raise JWTKeyRejectedError("JWT signing key has been revoked")
        try:
            return self.keys[key_id]
        except KeyError as exc:
            raise JWTKeyRejectedError("JWT signing key is unknown") from exc


def _parse_keys(serialized: str) -> dict[str, str]:
    try:
        value = json.loads(serialized)
    except json.JSONDecodeError as exc:
        raise JWTKeyConfigurationError("DOR_JWT_SIGNING_KEYS must be valid JSON") from exc
    if not isinstance(value, dict) or not value:
        raise JWTKeyConfigurationError("DOR_JWT_SIGNING_KEYS must be a non-empty JSON object")
    keys: dict[str, str] = {}
    for key_id, secret in value.items():
        _validate_key_id(key_id)
        if not isinstance(secret, str) or not secret:
            raise JWTKeyConfigurationError("JWT signing keys must be non-empty strings")
        keys[key_id] = secret
    return keys


def _validate_key_id(key_id: object) -> None:
    if not isinstance(key_id, str) or not _KEY_ID_PATTERN.fullmatch(key_id):
        raise JWTKeyConfigurationError(
            "JWT key IDs must be 1-64 safe alphanumeric, dot, underscore, or hyphen characters"
        )
