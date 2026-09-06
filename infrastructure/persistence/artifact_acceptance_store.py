"""Tenant-scoped append-only storage for multi-spec artifact acceptances."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from phase4.artifact_acceptance import MultiSpecArtifactAcceptance

from .artifact_acceptance_models import ArtifactAcceptanceModel


class ArtifactAcceptanceConflictError(RuntimeError):
    """A command or bundle conflicts with an existing immutable acceptance."""


class ArtifactAcceptanceStore:
    def __init__(self, session: Session) -> None:
        self.session = session

    def get(
        self,
        *,
        organization_id: str,
        acceptance_id: str,
    ) -> ArtifactAcceptanceModel | None:
        return self.session.scalar(
            select(ArtifactAcceptanceModel).where(
                ArtifactAcceptanceModel.organization_id == organization_id,
                ArtifactAcceptanceModel.acceptance_id == acceptance_id,
            )
        )

    def get_for_command(
        self,
        *,
        organization_id: str,
        command_id: str,
    ) -> ArtifactAcceptanceModel | None:
        return self.session.scalar(
            select(ArtifactAcceptanceModel).where(
                ArtifactAcceptanceModel.organization_id == organization_id,
                ArtifactAcceptanceModel.command_id == command_id,
            )
        )

    def get_for_bundle(
        self,
        *,
        organization_id: str,
        bundle_fingerprint: str,
        contract_fingerprint: str,
    ) -> ArtifactAcceptanceModel | None:
        return self.session.scalar(
            select(ArtifactAcceptanceModel).where(
                ArtifactAcceptanceModel.organization_id == organization_id,
                ArtifactAcceptanceModel.bundle_fingerprint == bundle_fingerprint,
                ArtifactAcceptanceModel.contract_fingerprint == contract_fingerprint,
            )
        )

    def add(
        self,
        *,
        command_id: str,
        acceptance: MultiSpecArtifactAcceptance,
    ) -> ArtifactAcceptanceModel:
        existing_command = self.get_for_command(
            organization_id=acceptance.organization_id,
            command_id=command_id,
        )
        if existing_command is not None:
            if existing_command.bundle_fingerprint != acceptance.bundle_fingerprint:
                raise ArtifactAcceptanceConflictError(
                    "command_id is already bound to another acceptance bundle"
                )
            return existing_command
        existing_bundle = self.get_for_bundle(
            organization_id=acceptance.organization_id,
            bundle_fingerprint=acceptance.bundle_fingerprint,
            contract_fingerprint=acceptance.contract_fingerprint,
        )
        if existing_bundle is not None:
            return existing_bundle
        payload = acceptance.canonical()
        row = ArtifactAcceptanceModel(
            acceptance_id=acceptance.acceptance_id,
            organization_id=acceptance.organization_id,
            repository=acceptance.repository,
            artifact_set_fingerprint=acceptance.artifact_set_fingerprint,
            bundle_fingerprint=acceptance.bundle_fingerprint,
            contract_id=acceptance.contract_id,
            contract_version=acceptance.contract_version,
            contract_fingerprint=acceptance.contract_fingerprint,
            command_id=command_id,
            accepted_by=acceptance.accepted_by,
            accepted_at=acceptance.accepted_at,
            rationale=acceptance.rationale,
            manifest_ids=[item.manifest_id for item in acceptance.specs],
            specs_payload=list(payload["specs"]),
            acceptance_payload=payload,
        )
        self.session.add(row)
        self.session.flush()
        return row

    @staticmethod
    def response_payload(row: ArtifactAcceptanceModel) -> dict[str, Any]:
        return dict(row.acceptance_payload)


__all__ = ["ArtifactAcceptanceConflictError", "ArtifactAcceptanceStore"]
