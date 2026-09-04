from dashboard.integration_view_model import normalize_redmine_health


def test_redmine_health_view_requires_all_three_verified_flags() -> None:
    status = normalize_redmine_health(
        {
            "configured": True,
            "reachable": True,
            "verified": True,
            "base_url": "https://redmine.example.test",
            "project_id": "project-a",
            "checked_at": "2026-09-04T19:00:00Z",
            "error": None,
            "missing_configuration": [],
        }
    )

    assert status["status"] == "verified"
    assert status["level"] == "success"
    assert status["verified"] is True
    assert "verificeret" in status["message"]


def test_redmine_health_view_surfaces_missing_server_configuration() -> None:
    status = normalize_redmine_health(
        {
            "configured": False,
            "reachable": False,
            "verified": False,
            "error": "not_configured",
            "missing_configuration": ["REDMINE_API_KEY"],
        }
    )

    assert status["status"] == "not_configured"
    assert status["level"] == "warning"
    assert "REDMINE_API_KEY" in status["message"]


def test_redmine_health_view_never_promotes_reachable_auth_failure() -> None:
    status = normalize_redmine_health(
        {
            "configured": True,
            "reachable": True,
            "verified": False,
            "error": "authentication_failed",
        }
    )

    assert status["status"] == "authentication_failed"
    assert status["level"] == "error"
    assert status["verified"] is False


def test_redmine_health_view_fails_closed_on_malformed_payload() -> None:
    status = normalize_redmine_health({"verified": True})

    assert status["status"] == "not_configured"
    assert status["level"] == "warning"
    assert status["verified"] is True
    assert "verificeret" not in status["message"].lower()
