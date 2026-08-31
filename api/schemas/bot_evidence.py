"""Stable read-only envelope for governed multi-bot evidence."""

from typing import Any

from pydantic import BaseModel, ConfigDict


class EvidenceResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    organization_id: str
    evidence_type: str
    evidence_id: str
    fingerprint: str
    payload: dict[str, Any]
