"""DOR Runtime API application entrypoint."""

from typing import Annotated

from fastapi import Depends, FastAPI

from api.auth import User, get_current_active_user
from api.endpoints import auth, control_plane, decisions, implementation_agent, workflows
from monitoring.tracer import configure_tracing

app = FastAPI(
    title="Digital Organization Runtime (DOR)",
    version="0.1.0",
    description="Canonical runtime API for organization-scoped workflow execution.",
)
configure_tracing(app)


@app.get("/health", tags=["system"])
async def health() -> dict:
    """Return a minimal liveness response without initializing persistence."""
    return {"status": "ok"}


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
app.include_router(workflows.router, dependencies=[Depends(get_current_active_user)])
app.include_router(
    implementation_agent.router,
    dependencies=[Depends(get_current_active_user)],
)
app.include_router(
    decisions.router,
    dependencies=[Depends(get_current_active_user)],
)
