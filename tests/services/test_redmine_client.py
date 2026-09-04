from __future__ import annotations

import requests

from services.redmine_client import check_redmine_health


class FakeResponse:
    def __init__(self, status_code: int, payload=None, text: str = "") -> None:
        self.status_code = status_code
        self._payload = payload
        self.text = text
        self.ok = 200 <= status_code < 400

    def json(self):
        if isinstance(self._payload, Exception):
            raise self._payload
        return self._payload


class FakeSession:
    def __init__(self, response=None, error: Exception | None = None) -> None:
        self.response = response
        self.error = error
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        if self.error is not None:
            raise self.error
        return self.response


def test_redmine_health_fails_closed_when_configuration_is_missing(monkeypatch) -> None:
    for name in ("REDMINE_URL", "REDMINE_API_KEY", "REDMINE_PROJECT_ID"):
        monkeypatch.delenv(name, raising=False)

    result = check_redmine_health()

    assert result["configured"] is False
    assert result["reachable"] is False
    assert result["verified"] is False
    assert result["error"] == "not_configured"
    assert set(result["missing_configuration"]) == {
        "REDMINE_URL",
        "REDMINE_API_KEY",
        "REDMINE_PROJECT_ID",
    }


def test_redmine_health_verifies_authenticated_project_response() -> None:
    session = FakeSession(
        response=FakeResponse(
            200,
            {"project": {"id": 42, "identifier": "digital-medarbejdere"}},
        )
    )

    result = check_redmine_health(
        session=session,
        base_url="https://redmine.example.test/root/",
        api_key="super-secret-key",
        project_id="digital medarbejdere",
    )

    assert result["configured"] is True
    assert result["reachable"] is True
    assert result["verified"] is True
    assert result["error"] is None
    assert result["base_url"] == "https://redmine.example.test/root"
    assert result["project_id"] == "digital medarbejdere"
    url, kwargs = session.calls[0]
    assert url == (
        "https://redmine.example.test/root/projects/"
        "digital%20medarbejdere.json"
    )
    assert kwargs["headers"]["X-Redmine-API-Key"] == "super-secret-key"
    assert kwargs["allow_redirects"] is False


def test_redmine_health_marks_auth_failure_reachable_but_unverified() -> None:
    session = FakeSession(response=FakeResponse(401, {"error": "invalid api key"}))

    result = check_redmine_health(
        session=session,
        base_url="https://redmine.example.test",
        api_key="wrong-secret",
        project_id="project-a",
    )

    assert result["configured"] is True
    assert result["reachable"] is True
    assert result["verified"] is False
    assert result["error"] == "authentication_failed"


def test_redmine_health_marks_timeout_unreachable() -> None:
    session = FakeSession(error=requests.Timeout("secret timeout details"))

    result = check_redmine_health(
        session=session,
        base_url="https://redmine.example.test",
        api_key="secret-key",
        project_id="project-a",
    )

    assert result["reachable"] is False
    assert result["verified"] is False
    assert result["error"] == "timeout"


def test_redmine_health_never_returns_api_key_or_upstream_body() -> None:
    secret = "redmine-api-key-never-return"
    upstream_secret = "upstream-body-never-return"
    session = FakeSession(
        response=FakeResponse(
            500,
            {"error": upstream_secret},
            text=upstream_secret,
        )
    )

    result = check_redmine_health(
        session=session,
        base_url="https://redmine.example.test",
        api_key=secret,
        project_id="project-a",
    )

    serialized = repr(result)
    assert secret not in serialized
    assert upstream_secret not in serialized
    assert result["error"] == "upstream_error"


def test_redmine_health_rejects_credentialed_or_non_http_urls() -> None:
    for value in (
        "ftp://redmine.example.test",
        "https://user:pass@redmine.example.test",
        "not-a-url",
        "https://[",
    ):
        result = check_redmine_health(
            base_url=value,
            api_key="secret-key",
            project_id="project-a",
        )
        assert result["configured"] is False
        assert result["verified"] is False
        assert result["error"] == "invalid_configuration"
