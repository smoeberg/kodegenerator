"""Immutable inventory for the supported DOR HTTP API surface."""

from __future__ import annotations

from collections.abc import Iterable

CANONICAL_AUTHENTICATED_MODULES = (
    "api.endpoints.control_plane",
    "api.endpoints.swarm",
    "api.endpoints.swarm_operations",
    "api.endpoints.workflows",
    "api.endpoints.implementation_agent",
    "api.endpoints.decisions",
    "api.endpoints.pipeline",
    "api.endpoints.pipeline_gates",
    "api.endpoints.bot_evidence",
    "api.endpoints.bot_governance",
    "api.endpoints.bot_selection",
)

CANONICAL_REALTIME_MODULES = ("api.endpoints.swarm_websocket",)

# These modules were removed because their ID-only lookups did not derive
# tenant scope from the authenticated principal. The denylist is intentionally
# retained so CI detects accidental restoration under the old import paths.
RETIRED_LEGACY_MODULES = frozenset(
    {
        "api.endpoints.actors",
        "api.endpoints.artifacts",
        "api.endpoints.capabilities",
        "api.endpoints.governance_gates",
        "api.endpoints.intents",
        "api.endpoints.organizations",
        "api.endpoints.role_definitions",
        "api.endpoints.tasks",
        "api.endpoints.workflow_templates",
    }
)

RETIRED_LEGACY_PATH_PREFIXES = (
    "/actors",
    "/artifacts",
    "/capabilities",
    "/governance",
    "/intents",
    "/organizations",
    "/role-definitions",
    "/tasks",
    "/workflow-templates",
)


def validate_canonical_modules(module_names: Iterable[str]) -> None:
    """Fail startup when the authenticated router set drifts from inventory."""
    mounted = tuple(module_names)
    if mounted != CANONICAL_AUTHENTICATED_MODULES:
        unexpected = sorted(set(mounted) - set(CANONICAL_AUTHENTICATED_MODULES))
        missing = sorted(set(CANONICAL_AUTHENTICATED_MODULES) - set(mounted))
        raise RuntimeError(
            "canonical API router inventory mismatch; "
            f"unexpected={unexpected}, missing={missing}"
        )
