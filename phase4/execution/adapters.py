"""Explicit execution adapter contract for AI-4."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Protocol, Tuple

from .models import ExecutionRequest, GovernedDispatch


@dataclass(frozen=True)
class AdapterResult:
    """Normalized adapter output suitable for the immutable execution record."""

    output: Tuple[Tuple[str, str], ...] = ()

    @staticmethod
    def from_mapping(values: Mapping[str, object] | None) -> "AdapterResult":
        return AdapterResult(
            output=tuple(sorted((str(key), str(value)) for key, value in (values or {}).items()))
        )


class ExecutionAdapter(Protocol):
    """Protocol implemented by a trusted, statically registered adapter."""

    @property
    def adapter_id(self) -> str:
        ...

    @property
    def action(self) -> str:
        ...

    def execute(
        self,
        request: ExecutionRequest,
        *,
        dispatch: GovernedDispatch,
    ) -> AdapterResult | None:
        ...


class StaticExecutionAdapter:
    """Reference adapter that requires the governed AI-3 -> AI-4 dispatch."""

    def __init__(self, adapter_id: str, action: str, handler) -> None:
        if not adapter_id.strip() or not action.strip():
            raise ValueError("adapter_id and action must be non-empty")
        if not callable(handler):
            raise TypeError("handler must be callable")
        self._adapter_id = adapter_id
        self._action = action
        self._handler = handler

    @property
    def adapter_id(self) -> str:
        return self._adapter_id

    @property
    def action(self) -> str:
        return self._action

    def execute(
        self,
        request: ExecutionRequest,
        *,
        dispatch: GovernedDispatch | None = None,
    ) -> AdapterResult | None:
        if not isinstance(dispatch, GovernedDispatch):
            return None
        if not dispatch.is_verified or dispatch.request is not request:
            return None
        result = self._handler(request)
        if isinstance(result, AdapterResult):
            return result
        if isinstance(result, Mapping):
            return AdapterResult.from_mapping(result)
        raise TypeError("adapter handler must return AdapterResult or a mapping")
