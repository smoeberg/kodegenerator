"""Tenant-scoped append-only storage for authoritative delivery certificates."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from phase4.delivery_certification import DeliveryCertificate
from phase4.delivery_certificate import DeliveryVerificationCandidate

from .delivery_certificate_models import DeliveryCertificateModel


class DeliveryCertificateConflictError(RuntimeError):
    """A command/candidate binding conflicts with an existing immutable certificate."""


class DeliveryCertificateStore:
    def __init__(self, session: Session) -> None:
        self.session = session

    def get(
        self,
        *,
        organization_id: str,
        certificate_id: str,
    ) -> DeliveryCertificateModel | None:
        return self.session.scalar(
            select(DeliveryCertificateModel).where(
                DeliveryCertificateModel.organization_id == organization_id,
                DeliveryCertificateModel.certificate_id == certificate_id,
            )
        )

    def get_for_candidate(
        self,
        *,
        organization_id: str,
        candidate_id: str,
        contract_fingerprint: str,
    ) -> DeliveryCertificateModel | None:
        return self.session.scalar(
            select(DeliveryCertificateModel).where(
                DeliveryCertificateModel.organization_id == organization_id,
                DeliveryCertificateModel.candidate_id == candidate_id,
                DeliveryCertificateModel.contract_fingerprint == contract_fingerprint,
            )
        )

    def get_for_command(
        self,
        *,
        organization_id: str,
        command_id: str,
    ) -> DeliveryCertificateModel | None:
        return self.session.scalar(
            select(DeliveryCertificateModel).where(
                DeliveryCertificateModel.organization_id == organization_id,
                DeliveryCertificateModel.command_id == command_id,
            )
        )

    def add(
        self,
        *,
        command_id: str,
        candidate: DeliveryVerificationCandidate,
        certificate: DeliveryCertificate,
    ) -> DeliveryCertificateModel:
        if certificate.candidate_id != candidate.candidate_id:
            raise DeliveryCertificateConflictError(
                "certificate does not bind the supplied candidate"
            )
        existing_command = self.get_for_command(
            organization_id=candidate.organization_id,
            command_id=command_id,
        )
        if existing_command is not None:
            if existing_command.candidate_id != candidate.candidate_id:
                raise DeliveryCertificateConflictError(
                    "command_id is already bound to another delivery candidate"
                )
            return existing_command
        existing_candidate = self.get_for_candidate(
            organization_id=candidate.organization_id,
            candidate_id=candidate.candidate_id,
            contract_fingerprint=certificate.contract_fingerprint,
        )
        if existing_candidate is not None:
            return existing_candidate
        row = DeliveryCertificateModel(
            certificate_id=certificate.certificate_id,
            organization_id=certificate.organization_id,
            candidate_id=certificate.candidate_id,
            contract_id=certificate.contract_id,
            contract_version=certificate.contract_version,
            contract_fingerprint=certificate.contract_fingerprint,
            result=certificate.result.value,
            command_id=command_id,
            certified_by=certificate.certified_by,
            certified_at=certificate.certified_at,
            reason_codes=list(certificate.reason_codes),
            candidate_payload=candidate.canonical(),
            certificate_payload=certificate.canonical(),
        )
        self.session.add(row)
        self.session.flush()
        return row

    @staticmethod
    def response_payload(row: DeliveryCertificateModel) -> dict[str, Any]:
        return dict(row.certificate_payload)


__all__ = [
    "DeliveryCertificateConflictError",
    "DeliveryCertificateStore",
]
