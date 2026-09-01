"""DOR control-plane API entrypoint."""

from __future__ import annotations

import logging
import os
from typing import Annotated, Any

from fastapi import Depends, FastAPI, status
from fastapi.responses import JSONResponse

from api.api_surface import validate_canonical_modules
from infrastructure.persistence.database import Database
from monitoring.tracer import configure_tracing
from services.runtime_configuration import validate_runtime_configuration
from services.runtime_readiness import verify_database_readiness

# Determine environment
DOR_ENV = os.environ.get("DOR_ENV", "development").lower()
IS_PRODUCTION = DOR_ENV == "production"
logger = logging.getLogger(__name__)


def validate_production_security_configuration() -> None:
    """Fail startup when production authentication has no explicit secrets."""
    if not IS_PRODUCTION:
        return
    missing = [
        name
        for name in (
            "DOR_ADMIN_PASSWORD",
            "DOR_ADMIN_ORGANIZATION_ID",
            "DATABASE_URL",
        )
        if not os.environ.get(name, "").strip()
    ]
    if not (
        os.environ.get("DOR_JWT_SECRET_KEY", "").strip()
        or os.environ.get("DOR_JWT_SIGNING_KEYS", "").strip()
    ):
        missing.append("DOR_JWT_SECRET_KEY or DOR_JWT_SIGNING_KEYS")
    if missing:
        raise RuntimeError(
            "Missing required production security configuration: " + ", ".join(missing)
        )
    from services.jwt_keyring import JWTKeyRing

    JWTKeyRing.from_environment(production=True)


validate_production_security_configuration()
validate_runtime_configuration(role="api")

# Initialize database for health checks
_db = Database(os.environ.get("DATABASE_URL", "sqlite:///./dor_runtime.db"))

from api.auth import User, get_current_active_user  # noqa: E402
from api.endpoints import (  # noqa: E402
    auth,
    bot_evidence,
    bot_governance,
    bot_selection,
    control_plane,
    decisions,
    implementation_agent,
    pipeline,
    pipeline_gates,
    swarm,
    swarm_operations,
    swarm_websocket,
    workflows,
)

HAS_AUTH = True

app = FastAPI(
    title="Digital Organization Runtime (DOR)",
    version="0.1.0",
    docs_url=None if IS_PRODUCTION else "/docs",
    redoc_url=None if IS_PRODUCTION else "/redoc",
    openapi_url=None if IS_PRODUCTION else "/openapi.json",
)

configure_tracing(app)


@app.get("/health", tags=["system"])
async def health() -> dict[str, str]:
    """Return runtime liveness status without authenticating."""
    return {"status": "ok"}


@app.get("/health/ready", tags=["system"])
async def health_ready() -> Any:
    """Return readiness status including database connectivity check."""
    try:
        migration_head = verify_database_readiness(_db)
        return {
            "status": "ready",
            "database": "ok",
            "migration_head": migration_head,
        }
    except Exception:
        logger.exception("readiness database check failed")
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={"status": "error", "database": "error"},
        )


if HAS_AUTH:

    @app.get("/protected", tags=["system"])
    async def protected_route(
        current_user: Annotated[User, Depends(get_current_active_user)],
    ) -> dict:
        """Example authenticated endpoint."""
        return {"message": f"Hello, {current_user.username}!"}

    # Canonical router whitelist. Legacy adapters remain deliberately unmounted
    # until they derive identity and tenant scope from the verified principal.
    CANONICAL_AUTHENTICATED_ROUTERS = (
        control_plane.router,
        swarm.router,
        swarm_operations.router,
        workflows.router,
        implementation_agent.router,
        decisions.router,
        pipeline.router,
        pipeline_gates.router,
        bot_evidence.router,
        bot_governance.router,
        bot_selection.router,
    )
    validate_canonical_modules(
        (
            control_plane.__name__,
            swarm.__name__,
            swarm_operations.__name__,
            workflows.__name__,
            implementation_agent.__name__,
            decisions.__name__,
            pipeline.__name__,
            pipeline_gates.__name__,
            bot_evidence.__name__,
            bot_governance.__name__,
            bot_selection.__name__,
        )
    )

    app.include_router(auth.router)
    for canonical_router in CANONICAL_AUTHENTICATED_ROUTERS:
        app.include_router(
            canonical_router,
            dependencies=[Depends(get_current_active_user)],
        )
    # Realtime endpoints enforce the same JWT plus project access internally,
    # before accepting a WebSocket or opening an SSE response.
    app.include_router(swarm_websocket.router)
