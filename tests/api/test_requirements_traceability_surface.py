from api.endpoints.requirements_traceability import router


def test_requirement_traceability_router_exposes_create_and_read() -> None:
    operations = {
        (route.path, method)
        for route in router.routes
        for method in (getattr(route, "methods", ()) or ())
    }

    assert (
        "/api/v1/control-plane/requirement-traceability",
        "POST",
    ) in operations
    assert (
        "/api/v1/control-plane/requirement-traceability/{manifest_id}",
        "GET",
    ) in operations
