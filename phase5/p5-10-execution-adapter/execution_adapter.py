"""P5-10 controlled execution adapter boundary."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class AdapterPolicy:
    adapter_id: str
    authorized: bool = False


@dataclass(frozen=True)
class ExecutionResult:
    request_id: str
    resolution_id: str
    resolution_fingerprint: str
    status: str
    adapter_id: str
    outcome: Any


class ExecutionAdapter:
    """Validate and delegate one immutable execution request exactly once."""

    def execute(self, request: Any, policy: AdapterPolicy, adapter: Any) -> ExecutionResult:
        self._validate(request, policy, adapter)

        # Deliberately exactly one call. Adapter exceptions propagate unchanged.
        outcome = adapter.execute(request)

        return ExecutionResult(
            request_id=request.request_id,
            resolution_id=request.resolution_id,
            resolution_fingerprint=request.resolution_fingerprint,
            status="SUCCEEDED",
            adapter_id=policy.adapter_id,
            outcome=outcome,
        )

    @staticmethod
    def _validate(request: Any, policy: AdapterPolicy, adapter: Any) -> None:
        if request is None:
            raise ValueError("execution request is required")
        if not policy or not policy.adapter_id:
            raise PermissionError("explicit adapter identity is required")
        if not policy.authorized:
            raise PermissionError("execution adapter is not authorized")
        if adapter is None:
            raise ValueError("execution adapter is required")
        if getattr(request, "adapter_id", None) != policy.adapter_id:
            raise PermissionError("adapter identity does not match execution request")

        supported = getattr(adapter, "supported_kinds", None)
        if supported is None or request.execution_kind not in supported:
            raise ValueError("execution adapter does not support requested execution kind")
        if not callable(getattr(adapter, "execute", None)):
            raise ValueError("execution adapter has no executable operation")
