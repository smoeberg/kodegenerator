"""Context propagation for pipeline operations (thread-safe via ContextVar).

The provider carries an ``OrganizationContext`` (principal, actor, organization)
through claim → execute → complete worker flows without threading it through
every call signature.
"""

from __future__ import annotations

from contextvars import ContextVar
from typing import Optional

from runtime.context import OrganizationContext

logger = None  # placeholder to avoid import cost at module load

_org_context: ContextVar[Optional[OrganizationContext]] = ContextVar(
    "org_context",
    default=None,
)


class ContextProvider:
    """Provides OrganizationContext propagation for the pipeline."""

    @staticmethod
    def set(context: OrganizationContext) -> None:
        _org_context.set(context)

    @staticmethod
    def get() -> Optional[OrganizationContext]:
        return _org_context.get()

    @staticmethod
    def clear() -> None:
        _org_context.set(None)

    @staticmethod
    def require() -> OrganizationContext:
        context = _org_context.get()
        if context is None:
            raise RuntimeError("No OrganizationContext available in current context")
        return context
