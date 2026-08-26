"""DOR control-plane API entrypoint."""
from __future__ import annotations
import os
from typing import Annotated
from fastapi import Depends, FastAPI
from infrastructure.persistence.database import Database
from monitoring.tracer import configure_tracing
DOR_ENV=os.environ.get("DOR_ENV","development").lower(); IS_PRODUCTION=DOR_ENV=="production"; _db=Database()
if IS_PRODUCTION or os.environ.get("DOR_JWT_SECRET_KEY"):
    from api.auth import User,get_current_active_user
    from api.endpoints import auth,control_plane,decisions,implementation_agent,workflows,swarm
    HAS_AUTH=True
else: HAS_AUTH=False
app=FastAPI(title="Digital Organization Runtime (DOR)",version="0.1.0",docs_url=None if IS_PRODUCTION else "/docs",redoc_url=None if IS_PRODUCTION else "/redoc",openapi_url=None if IS_PRODUCTION else "/openapi.json")
configure_tracing(app)
@app.get("/health",tags=["system"])
async def health()->dict[str,str]: return {"status":"ok"}
@app.get("/health/ready",tags=["system"])
async def health_ready()->dict:
    try:
        with _db.session() as session: session.execute("SELECT 1")
        return {"status":"ready","database":"ok"}
    except Exception as e:return {"status":"not_ready","database":"error","error":str(e)}
if HAS_AUTH:
    @app.get("/protected",tags=["system"])
    async def protected_route(current_user:Annotated[User,Depends(get_current_active_user)])->dict:return {"message":f"Hello, {current_user.username}!"}
    app.include_router(auth.router)
    app.include_router(control_plane.router,dependencies=[Depends(get_current_active_user)])
    app.include_router(workflows.router,dependencies=[Depends(get_current_active_user)])
    app.include_router(implementation_agent.router,dependencies=[Depends(get_current_active_user)])
    app.include_router(decisions.router,dependencies=[Depends(get_current_active_user)])
    app.include_router(swarm.router,dependencies=[Depends(get_current_active_user)])
