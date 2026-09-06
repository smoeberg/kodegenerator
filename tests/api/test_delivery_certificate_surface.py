from api.endpoints.delivery_certificates import router


def test_delivery_certificate_router_exposes_certify_and_read() -> None:
    operations = {
        (route.path, method)
        for route in router.routes
        for method in (getattr(route, "methods", ()) or ())
    }

    assert (
        "/api/v1/control-plane/delivery-certificates",
        "POST",
    ) in operations
    assert (
        "/api/v1/control-plane/delivery-certificates/{certificate_id}",
        "GET",
    ) in operations
