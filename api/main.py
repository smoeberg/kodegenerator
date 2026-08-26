"""DOR control-plane API entrypoint."""
from __future__ import annotations

import os
from typing import Annotated

from fastapi import Depends, FastAPI

from infrastructure.persistence.database import Database
from monitoring.tracer import configure_tracing

# Determine environment
DOR_ENV = os.environ.get("DOR_ENV", "development").lower()
IS_PRODUCTION = DOR_ENV == "production"

# Initialize database for health checks
_db = Database()

# Import auth components (will fail if DOR_JWT_SECRET_KEY is missing in non-test env)
if IS_PRODUCTION or os.environ.get("DOR_JWT_SECRET_KEY"):
    from api.auth import User, get_current_active_user
    from api.endpoints import auth, control_plane, decisions, implementation_agent, swarm, swarm_operations, swarm_websocket, workflows
    HAS_AUTH = True
else:
    # Allow API to start without auth for test/development
    HAS_AUTH = False

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
            session.execute("SELECT 1")
        return {"status": "ready", "database": "ok"}
    except Exception as e:
        return {
            "status": "not_ready",
            "database": "error",
            "error": str(e)
        }


if HAS_AUTH:
    @app.get("/protected", tags=["system"])
    async def protected_route(
        current_user: Annotated[User, Depends(get_current_active_user)],
    ) -> dict:
        """Example authenticated endpoint."""
        return {"message": f"Hello, {current_user.username}!"}

    app.include_router(auth.router)
    app.include_router(
        control_plane.router,
        dependencies=[Depends(get_current_active_user)],
    )
    app.include_router(swarm.router, dependencies=[Depends(get_current_active_user)])
    app.include_router(swarm_operations.router, dependencies=[Depends(get_current_active_user)])
    # WebSocket/SSE hub — no global JWT Depends (handshake + optional ?token=)
    app.include_router(swarm_websocket.router)
    app.include_router(workflows.router, dependencies=[Depends(get_current_active_user)])
    app.include_router(
        implementation_agent.router,
        dependencies=[Depends(get_current_active_user)],
    )
    app.include_router(
        decisions.router,
        dependencies=[Depends(get_current_active_user)],
    )
