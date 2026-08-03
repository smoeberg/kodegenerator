"""DOR Runtime API application entrypoint."""

from fastapi import Depends, FastAPI

from api.auth import User, get_current_active_user
from api.endpoints import (
    actors,
    artifacts,
    auth,
    capabilities,
    intents,
    organizations,
    role_definitions,
    tasks,
    workflow_templates,
    workflows,
)

app = FastAPI(
    title="Digital Organization Runtime (DOR)",
    version="0.1.0",
    description="Runtime API for organizations, actors, intents, workflows and artifacts.",
)


@app.get("/health", tags=["system"])
async def health() -> dict:
    """Return a minimal liveness response."""
    return {"status": "ok"}


@app.get("/protected", tags=["system"])
async def protected_route(
    current_user: User = Depends(get_current_active_user),
) -> dict:
    """Example authenticated endpoint."""
    return {"message": f"Hello, {current_user.username}!"}


app.include_router(auth.router)

# All DOR resources require an authenticated user.
_authenticated = [Depends(get_current_active_user)]
app.include_router(organizations.router, dependencies=_authenticated)
app.include_router(actors.router, dependencies=_authenticated)
app.include_router(role_definitions.router, dependencies=_authenticated)
app.include_router(capabilities.router, dependencies=_authenticated)
app.include_router(intents.router, dependencies=_authenticated)
app.include_router(workflows.router, dependencies=_authenticated)
app.include_router(tasks.router, dependencies=_authenticated)
app.include_router(artifacts.router, dependencies=_authenticated)
app.include_router(workflow_templates.router, dependencies=_authenticated)
