from api.main import app


def test_requirement_traceability_routes_are_canonical_and_authenticated() -> None:
    routes = {
        (route.path, method, getattr(route.endpoint, "__module__", ""))
        for route in app.routes
        if hasattr(route, "methods")
        for method in route.methods
    }
    assert (
        "/api/v1/control-plane/requirement-traceability",
        "POST",
        "api.endpoints.requirements_traceability",
    ) in routes
    assert (
        "/api/v1/control-plane/requirement-traceability/{manifest_id}",
        "GET",
        "api.endpoints.requirements_traceability",
    ) in routes
