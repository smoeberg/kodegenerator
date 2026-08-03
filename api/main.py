# api/main.py (Udvidet)
from api.auth import get_current_active_user
from fastapi import Depends

# Tilføj autentificering til alle endpoints
@app.get("/protected")
async def protected_route(current_user: User = Depends(get_current_active_user)):
    return {"message": f"Hello, {current_user.username}!"}

# Opdater alle routers til at kræve autentificering
from api.endpoints import (
    organizations, actors, role_definitions, capabilities,
    intents, workflows, tasks, artifacts, workflow_templates, auth
)

app.include_router(auth.router)
app.include_router(organizations.router, dependencies=[Depends(get_current_active_user)])
app.include_router(actors.router, dependencies=[Depends(get_current_active_user)])
app.include_router(role_definitions.router, dependencies=[Depends(get_current_active_user)])
app.include_router(capabilities.router, dependencies=[Depends(get_current_active_user)])
app.include_router(intents.router, dependencies=[Depends(get_current_active_user)])
app.include_router(workflows.router, dependencies=[Depends(get_current_active_user)])
app.include_router(tasks.router, dependencies=[Depends(get_current_active_user)])
app.include_router(artifacts.router, dependencies=[Depends(get_current_active_user)])
app.include_router(workflow_templates.router, dependencies=[Depends(get_current_active_user)])
