"""DOR control-plane API entrypoint."""
from __future__ import annotations

import logging
import os
from typing import Annotated

from fastapi import Depends, FastAPI
from sqlalchemy import text

from infrastructure.persistence.database import Database
from monitoring.tracer import configure_tracing

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
        for name in ("DOR_JWT_SECRET_KEY", "DOR_ADMIN_PASSWORD")
        if not os.environ.get(name, "").strip()
    ]
    if missing:
        raise RuntimeError(
            "Missing required production security configuration: "
            + ", ".join(missing)
        )


validate_production_security_configuration()

# Initialize database for health checks
_db = Database()

from api.auth import User, get_current_active_user
from api.endpoints import (
    auth,
    control_plane,
    decisions,
    implementation_agent,
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
async def health_ready() -> dict:
    """Return readiness status including database connectivity check."""
    try:
        with _db.session() as session:
            session.execute(text("SELECT 1"))
        return {"status": "ready", "database": "ok"}
    except Exception:
        logger.exception("readiness database check failed")
        return {"status": "error", "database": "error"}


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
        pipeline_gates.router,
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
