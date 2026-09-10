"""Thin validated API facade for the independent DOR Customer Portal."""
from __future__ import annotations

from typing import Any, Mapping

from dashboard.api_client import DORAPIClient, DORAPIError


class CustomerContractError(RuntimeError):
    """Authoritative API response is missing required customer-facing structure."""


class CustomerAPI:
    """Expose only read paths and existing governed decision commands."""

    def __init__(self, token: str | None = None, *, client: DORAPIClient | None = None) -> None:
        self._client = client or DORAPIClient(token=token)

    def login(self, username: str, password: str) -> str:
        return self._client.login(username, password)

    def active_organization(self) -> dict[str, Any]:
        payload = self._client.get("/api/v1/control-plane/organizations")
        if not isinstance(payload, Mapping):
            raise CustomerContractError("organization catalog is malformed")
        active_id = str(payload.get("active_organization_id") or "").strip()
        organizations = payload.get("organizations")
        if not active_id or not isinstance(organizations, list):
            raise CustomerContractError("active organization cannot be established")
        for item in organizations:
            if isinstance(item, Mapping) and str(item.get("id") or "").strip() == active_id:
                return dict(item)
        raise CustomerContractError("active organization is not in the authenticated catalog")

    def projects(self, organization_id: str) -> list[dict[str, Any]]:
        payload = self._client.get(
            "/api/v1/control-plane/projects",
            params={"organization_id": organization_id},
        )
        if not isinstance(payload, Mapping) or payload.get("organization_id") != organization_id:
            raise CustomerContractError("project catalog tenant scope is inconsistent")
        raw = payload.get("projects")
        if not isinstance(raw, list):
            raise CustomerContractError("project catalog is malformed")
        projects: list[dict[str, Any]] = []
        for item in raw:
            if not isinstance(item, Mapping):
                raise CustomerContractError("project catalog contains malformed entry")
            project = dict(item)
            if str(project.get("organization_id") or "") != organization_id:
                raise CustomerContractError("project crossed authenticated tenant scope")
            if not str(project.get("project_id") or "").strip():
                raise CustomerContractError("project identity is missing")
            projects.append(project)
        return projects

    def project_execution(self, project: Mapping[str, Any]) -> dict[str, Any] | None:
        project_id = str(project.get("project_id") or "").strip()
        fingerprint = str(project.get("active_plan_request_fingerprint") or "").strip()
        if not project_id or len(fingerprint) != 64:
            return None
        try:
            payload = self._client.get(
                f"/api/v1/control-plane/projects/{project_id}/execution",
                params={"plan_request_fingerprint": fingerprint},
            )
        except DORAPIError as exc:
            if exc.status_code == 404:
                return None
            raise
        if not isinstance(payload, Mapping):
            raise CustomerContractError("project execution response is malformed")
        result = dict(payload)
        if result.get("project_id") != project_id:
            raise CustomerContractError("execution project provenance mismatch")
        if result.get("plan_request_fingerprint") != fingerprint:
            raise CustomerContractError("execution plan provenance mismatch")
        if not str(result.get("workflow_id") or "").strip():
            raise CustomerContractError("execution workflow identity is missing")
        return result

    def gates(self, workflow_id: str) -> list[dict[str, Any]]:
        payload = self._client.get(f"/api/v1/execution/{workflow_id}/gates")
        if not isinstance(payload, list):
            raise CustomerContractError("gate list is malformed")
        gates: list[dict[str, Any]] = []
        for item in payload:
            if not isinstance(item, Mapping) or not str(item.get("id") or "").strip():
                raise CustomerContractError("gate entry is malformed")
            decision = item.get("decision")
            if decision not in {None, "approved", "rejected"}:
                raise CustomerContractError("gate decision state is unknown")
            gates.append(dict(item))
        return gates

    def proposals(self, workflow_id: str) -> list[dict[str, Any]]:
        payload = self._client.get(f"/api/v1/execution/{workflow_id}/proposals")
        if not isinstance(payload, list):
            raise CustomerContractError("proposal list is malformed")
        proposals: list[dict[str, Any]] = []
        for item in payload:
            if not isinstance(item, Mapping):
                raise CustomerContractError("proposal entry is malformed")
            proposal = dict(item)
            if str(proposal.get("workflow_id") or "") != workflow_id:
                raise CustomerContractError("proposal execution provenance mismatch")
            if not str(proposal.get("id") or "").strip():
                raise CustomerContractError("proposal identity is missing")
            proposals.append(proposal)
        return proposals

    def project_events(self, project_id: str, organization_id: str) -> list[dict[str, Any]]:
        payload = self._client.get(
            f"/api/v1/control-plane/projects/{project_id}/events",
            params={"organization_id": organization_id, "limit": 100},
        )
        if not isinstance(payload, Mapping) or payload.get("project_id") != project_id:
            raise CustomerContractError("project event response is malformed")
        raw = payload.get("events")
        if not isinstance(raw, list):
            raise CustomerContractError("project event list is malformed")
        events: list[dict[str, Any]] = []
        for item in raw:
            if not isinstance(item, Mapping):
                raise CustomerContractError("project event is malformed")
            event = dict(item)
            if str(event.get("organization_id") or "") != organization_id:
                raise CustomerContractError("project event crossed tenant scope")
            events.append(event)
        return events

    def decide(self, workflow_id: str, gate_id: str, decision: str) -> dict[str, Any]:
        if decision not in {"approved", "rejected"}:
            raise ValueError("decision must be approved or rejected")
        payload = self._client.post(
            f"/api/v1/execution/{workflow_id}/gates/decide",
            json={"gate_id": gate_id, "decision": decision},
        )
        if not isinstance(payload, Mapping):
            raise CustomerContractError("decision response is malformed")
        result = dict(payload)
        if (
            result.get("workflow_id") != workflow_id
            or result.get("gate_id") != gate_id
            or result.get("decision") != decision
        ):
            raise CustomerContractError("decision response does not match submitted command")
        return result

    def request_changes(self, workflow_id: str, gate_id: str, reason: str) -> dict[str, Any]:
        canonical_reason = reason.strip()
        if not canonical_reason:
            raise ValueError("reason is required")
        payload = self._client.post(
            f"/api/v1/execution/{workflow_id}/gates/rework",
            json={"gate_id": gate_id, "reason": canonical_reason},
        )
        if not isinstance(payload, Mapping):
            raise CustomerContractError("rework response is malformed")
        result = dict(payload)
        if result.get("workflow_id") != workflow_id or result.get("gate_id") != gate_id:
            raise CustomerContractError("rework response does not match submitted command")
        return result


__all__ = ["CustomerAPI", "CustomerContractError"]
