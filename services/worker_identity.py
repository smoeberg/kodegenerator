"""Provision and authenticate tenant-bound worker service accounts."""

from __future__ import annotations

import hashlib
import hmac
import re
import secrets
from dataclasses import dataclass
from datetime import datetime, timezone

from domain.authority import Capability
from infrastructure.persistence.database import apply_tenant_context
from infrastructure.persistence.worker_identity_models import (
    WorkerServiceIdentityModel,
)

_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_ITERATIONS = 600_000


class WorkerIdentityError(PermissionError):
    """A worker credential or identity binding is invalid."""


class WorkerIdentityConflictError(RuntimeError):
    """Provisioning would silently change an existing worker identity."""


@dataclass(frozen=True)
class WorkerPrincipal:
    organization_id: str
    service_id: str
    instance_id: str
    capabilities: tuple[str, ...]
    credential_version: int

    def __post_init__(self) -> None:
        for name in ("organization_id", "service_id", "instance_id"):
            if not _ID.fullmatch(getattr(self, name)):
                raise ValueError(f"{name} must be a canonical identifier")
        if self.capabilities != tuple(sorted(set(self.capabilities))):
            raise ValueError("worker capabilities must be sorted and unique")

    @property
    def worker_id(self) -> str:
        value = f"{self.service_id}@{self.instance_id}"
        if len(value) > 128:
            raise ValueError("effective worker ID exceeds 128 characters")
        return value


class WorkerIdentityStore:
    def __init__(self, session_factory) -> None:
        self._sessions = session_factory

    def provision(
        self,
        *,
        organization_id: str,
        service_id: str,
        credential: str,
        capabilities: tuple[str, ...],
    ) -> None:
        organization_id, service_id, capabilities = _validate_identity(
            organization_id, service_id, credential, capabilities
        )
        existing = self._get(organization_id, service_id)
        if existing is not None:
            if (
                existing.capabilities != list(capabilities)
                or existing.disabled
                or not _verify_credential(credential, existing.credential_hash)
            ):
                raise WorkerIdentityConflictError(
                    "worker identity already exists with different security state"
                )
            return
        now = datetime.now(timezone.utc)
        with self._sessions() as session, session.begin():
            apply_tenant_context(session, organization_id)
            session.add(
                WorkerServiceIdentityModel(
                    organization_id=organization_id,
                    service_id=service_id,
                    credential_hash=_hash_credential(credential),
                    capabilities=list(capabilities),
                    disabled=False,
                    credential_version=1,
                    created_at=now,
                    updated_at=now,
                )
            )

    def authenticate(
        self,
        *,
        organization_id: str,
        service_id: str,
        instance_id: str,
        credential: str,
    ) -> WorkerPrincipal:
        if not _ID.fullmatch(instance_id):
            raise WorkerIdentityError("worker instance identity is invalid")
        row = self._get(organization_id, service_id)
        if (
            row is None
            or row.disabled
            or not _verify_credential(credential, row.credential_hash)
        ):
            raise WorkerIdentityError("worker authentication failed")
        return WorkerPrincipal(
            organization_id=row.organization_id,
            service_id=row.service_id,
            instance_id=instance_id,
            capabilities=tuple(row.capabilities),
            credential_version=row.credential_version,
        )

    def _get(
        self, organization_id: str, service_id: str
    ) -> WorkerServiceIdentityModel | None:
        if not _ID.fullmatch(organization_id) or not _ID.fullmatch(service_id):
            raise WorkerIdentityError("worker identity is invalid")
        with self._sessions() as session:
            apply_tenant_context(session, organization_id)
            return session.get(
                WorkerServiceIdentityModel, (organization_id, service_id)
            )


def _validate_identity(
    organization_id: str,
    service_id: str,
    credential: str,
    capabilities: tuple[str, ...],
) -> tuple[str, str, tuple[str, ...]]:
    if not _ID.fullmatch(organization_id) or not _ID.fullmatch(service_id):
        raise ValueError("worker organization and service IDs must be canonical")
    if len(credential) < 32:
        raise ValueError("worker credential must contain at least 32 characters")
    normalized = tuple(sorted(set(capabilities)))
    if not normalized or normalized != capabilities:
        raise ValueError("worker capabilities must be sorted, unique and non-empty")
    for item in normalized:
        Capability(item)
    return organization_id, service_id, normalized


def _hash_credential(credential: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", credential.encode(), salt, _ITERATIONS)
    return f"pbkdf2_sha256${_ITERATIONS}${salt.hex()}${digest.hex()}"


def _verify_credential(credential: str, encoded: str) -> bool:
    try:
        scheme, iterations, salt_hex, digest_hex = encoded.split("$", 3)
        if scheme != "pbkdf2_sha256":
            return False
        digest = hashlib.pbkdf2_hmac(
            "sha256",
            credential.encode(),
            bytes.fromhex(salt_hex),
            int(iterations),
        )
    except (TypeError, ValueError):
        return False
    return hmac.compare_digest(digest.hex(), digest_hex)
