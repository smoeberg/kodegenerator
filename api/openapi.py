"""OpenAPI / Swagger configuration for Digital Organization Runtime (DOR)."""

from fastapi.openapi.utils import get_openapi

def custom_openapi(app):
    if app.openapi_schema:
        return app.openapi_schema

    openapi_schema = get_openapi(
        title="Digital Organization Runtime (DOR) API",
        version="1.0.0",
        description="Comprehensive REST API for managing Digital Employees, Workflows, Governance Gates, and Artifacts.",
        routes=app.routes,
    )
    openapi_schema["info"]["x-logo"] = {
        "url": "https://fastapi.tiangolo.com/img/logo-margin/logo-teal.png"
    }
    app.openapi_schema = openapi_schema
    return app.openapi_schema
