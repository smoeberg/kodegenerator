from unittest.mock import Mock, patch

import pytest

from dashboard.api_client import DORAPIClient, DORAPIError


def test_client_uses_bearer_token():
    client = DORAPIClient(base_url="http://api:8000", token="abc")
    response = Mock(status_code=200, ok=True)
    response.json.return_value = {"ok": True}
    with patch.object(client.session, "request", return_value=response) as request:
        assert client.get("/health") == {"ok": True}
    assert request.call_args.kwargs["headers"]["Authorization"] == "Bearer abc"


def test_client_turns_401_into_explicit_error():
    client = DORAPIClient(base_url="http://api:8000", token="expired")
    response = Mock(status_code=401, ok=False)
    response.json.return_value = {"detail": "expired"}
    with patch.object(client.session, "request", return_value=response):
        with pytest.raises(DORAPIError) as exc:
            client.get("/protected")
    assert exc.value.status_code == 401


def test_stream_session_keeps_cookie_in_client_session():
    client = DORAPIClient(base_url="http://api:8000", token="abc")
    response = Mock(status_code=200, ok=True)
    response.json.return_value = {"workflow_id": "wf-1"}
    with patch.object(client.session, "request", return_value=response) as request:
        client.create_stream_session("wf-1")
    assert request.call_args.args[:2] == ("POST", "http://api:8000/api/v1/execution/stream-session/wf-1")


def test_stream_urls_never_contain_access_token():
    client = DORAPIClient(base_url="https://dor.example", token="secret-token")
    assert client.stream_url("wf-1", websocket=True) == "wss://dor.example/api/v1/execution/ws/wf-1"
    assert client.stream_url("wf-1", websocket=False) == "https://dor.example/api/v1/execution/events/wf-1"
    assert "secret-token" not in client.stream_url("wf-1", websocket=True)
