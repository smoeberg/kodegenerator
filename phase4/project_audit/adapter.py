"""Provider-neutral AI-4 adapter for evidence-backed project audits."""

from __future__ import annotations

from collections.abc import Iterable
from threading import RLock
from typing import Protocol

from phase4.execution.adapters import AdapterResult
from phase4.execution.models import ExecutionRequest

from .models import (
    PROJECT_AUDIT_ACTION,
    ProjectAuditCandidate,
    ProjectAuditReport,
    ProjectAuditRequest,
)


class ProjectAuditAdapterError(Exception):
    """Base error raised by the project-audit adapter boundary."""


class DuplicateProjectAuditRequestError(ProjectAuditAdapterError):
    """The same immutable audit request was registered more than once."""


class ProjectAuditRequestNotFoundError(ProjectAuditAdapterError):
    """An execution request referenced no registered audit request."""


class ProjectAuditRequestBindingError(ProjectAuditAdapterError):
    """AI-4 input does not match the registered audit request."""


class ProjectAuditReportNotFoundError(ProjectAuditAdapterError):
    """No validated audit report has the requested identity."""


class ProjectAuditProvider(Protocol):
    """Opaque reasoning boundary; model SDKs live outside this contract."""

    @property
    def provider_id(self) -> str: ...

    def audit_project(self, request: ProjectAuditRequest) -> ProjectAuditCandidate: ...


class ProjectAuditExecutionAdapter:
    """Trusted AI-4 boundary that validates and records advisory audit reports."""

    def __init__(
        self,
        *,
        adapter_id: str,
        provider: ProjectAuditProvider,
        requests: Iterable[ProjectAuditRequest] = (),
    ) -> None:
        if not isinstance(adapter_id, str) or not adapter_id.strip():
            raise ValueError("adapter_id must be a non-empty string")
        provider_id = getattr(provider, "provider_id", None)
        if not isinstance(provider_id, str) or not provider_id.strip():
            raise ValueError("provider must declare a non-empty provider_id")
        if not callable(getattr(provider, "audit_project", None)):
            raise TypeError("provider must implement audit_project")
        self._adapter_id = adapter_id
        self._provider = provider
        self._provider_id = provider_id
        self._requests: dict[str, ProjectAuditRequest] = {}
        self._reports: dict[str, ProjectAuditReport] = {}
        self._report_by_request: dict[str, str] = {}
        self._lock = RLock()
        for request in requests:
            self.register_request(request)

    @property
    def adapter_id(self) -> str:
        return self._adapter_id

    @property
    def action(self) -> str:
        return PROJECT_AUDIT_ACTION

    def register_request(self, request: ProjectAuditRequest) -> None:
        if not isinstance(request, ProjectAuditRequest):
            raise TypeError("request must be a ProjectAuditRequest")
        fingerprint = request.request_fingerprint
        with self._lock:
            if fingerprint in self._requests:
                raise DuplicateProjectAuditRequestError(fingerprint)
            self._requests[fingerprint] = request

    def execute(self, request: ExecutionRequest) -> AdapterResult:
        if not isinstance(request, ExecutionRequest):
            raise TypeError("request must be an ExecutionRequest")
        fingerprint = dict(request.parameters).get("audit_request_fingerprint")
        if fingerprint is None:
            raise ProjectAuditRequestBindingError(
                "execution request is missing the audit request fingerprint"
            )
        with self._lock:
            audit_request = self._requests.get(fingerprint)
            if audit_request is None:
                raise ProjectAuditRequestNotFoundError(fingerprint)
            self._validate_binding(request, audit_request)

            existing_id = self._report_by_request.get(fingerprint)
            if existing_id is not None:
                return self._result_for(self._reports[existing_id])

            candidate = self._provider.audit_project(audit_request)
            if not isinstance(candidate, ProjectAuditCandidate):
                raise TypeError("provider must return ProjectAuditCandidate")
            report = ProjectAuditReport(
                request=audit_request,
                provider_id=self._provider_id,
                candidate=candidate,
            )
            self._reports[report.report_id] = report
            self._report_by_request[fingerprint] = report.report_id
            return self._result_for(report)

    def get_report(self, report_id: str) -> ProjectAuditReport:
        with self._lock:
            try:
                return self._reports[report_id]
            except KeyError as exc:
                raise ProjectAuditReportNotFoundError(report_id) from exc

    def reports(self) -> tuple[ProjectAuditReport, ...]:
        with self._lock:
            return tuple(self._reports[key] for key in sorted(self._reports))

    @staticmethod
    def _validate_binding(
        execution_request: ExecutionRequest,
        audit_request: ProjectAuditRequest,
    ) -> None:
        expected = audit_request.execution_request(
            idempotency_key=execution_request.idempotency_key
        )
        for field_name in (
            "request_id",
            "agent_identity",
            "action",
            "resource",
            "context_packet_id",
            "parameters",
        ):
            if getattr(execution_request, field_name) != getattr(expected, field_name):
                raise ProjectAuditRequestBindingError(
                    f"execution {field_name} does not match the registered audit request"
                )

    @staticmethod
    def _result_for(report: ProjectAuditReport) -> AdapterResult:
        return AdapterResult(
            output=(
                ("authoritative", "false"),
                ("evidence_bundle_id", report.request.evidence_bundle.bundle_id),
                ("finding_count", str(len(report.findings))),
                ("provider_id", report.provider_id),
                ("recommendation", report.recommendation.value),
                ("report_id", report.report_id),
                ("request_fingerprint", report.request_fingerprint),
            )
        )
