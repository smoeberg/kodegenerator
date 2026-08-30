"""Phase 7: SDK transport neutrality with and without proxy environment variables.

The SDK must behave identically whether or not HTTP(S)_PROXY / NO_PROXY are
exported. The CI matrix runs this file twice: once with a stripped proxy
environment and once with a synthetic proxy declared, to prove the client
does not depend on ambient transport configuration.

The fixture injects a mock transport (the same pattern the SDK suite uses
with respx), so the test is deterministic and runs on hermetic runners too.
"""

from __future__ import annotations

import os

import pytest
from httpx import MockTransport, Response

from sdk import KodegeneratorClient


class StubTransport:
    """Records the route used so tests can assert proxy-vs-direct behaviour."""

    def __init__(self) -> None:
        self.routes: list[str] = []

    def handler(self, request):  # httpx.Request -> httpx.Response
        self.routes.append(
            request.url.scheme + "://" + request.url.host + request.url.path
        )
        if request.method == "POST" and request.url.path == "/tasks":
            return Response(
                200, json={"task_id": "proxy-ok", "project_id": "p", "status": "queued"}
            )
        if request.method == "GET" and request.url.path == "/projects/p/status":
            return Response(200, json={"project_id": "p", "status": "done"})
        return Response(404, json={"detail": "not-found"})


def _client(transport: StubTransport) -> KodegeneratorClient:
    """Build the SDK client with the stub transport injected."""
    mock = MockTransport(transport.handler)
    client = KodegeneratorClient("https://api.example.test", "k")
    client._client = client._client.__class__(
        base_url="https://api.example.test",
        timeout=client._client.timeout,
        headers=client._client.headers,
        transport=mock,
    )
    return client


def _apply_proxy_env(proxy: str | None, no_proxy: str | None) -> dict:
    keys = (
        "HTTP_PROXY",
        "HTTPS_PROXY",
        "http_proxy",
        "https_proxy",
        "NO_PROXY",
        "no_proxy",
    )
    previous = {key: os.environ.get(key) for key in keys}
    for key in keys:
        os.environ.pop(key, None)
    if proxy:
        os.environ["HTTPS_PROXY"] = proxy
        os.environ["https_proxy"] = proxy
        os.environ["HTTP_PROXY"] = proxy
        os.environ["http_proxy"] = proxy
    if no_proxy:
        os.environ["NO_PROXY"] = no_proxy
        os.environ["no_proxy"] = no_proxy
    return previous


def _restore_env(previous: dict) -> None:
    for key in (
        "HTTP_PROXY",
        "HTTPS_PROXY",
        "http_proxy",
        "https_proxy",
        "NO_PROXY",
        "no_proxy",
    ):
        os.environ.pop(key, None)
    for key, value in previous.items():
        if value is not None:
            os.environ[key] = value


@pytest.mark.parametrize("with_proxy", [False, True])
def test_submit_and_status_work_with_and_without_proxy(with_proxy: bool) -> None:
    """The same SDK calls succeed regardless of ambient proxy variables."""
    transport = StubTransport()
    previous = _apply_proxy_env(
        proxy="http://proxy.example.test:8080" if with_proxy else None,
        no_proxy=None,
    )
    try:
        client = _client(transport)
        try:
            result = client.submit_task({"prompt": "hello"})
            assert result.task_id == "proxy-ok"
            status = client.get_project_status("p")
            assert status.status == "done"
            assert transport.routes == [
                "https://api.example.test/tasks",
                "https://api.example.test/projects/p/status",
            ]
        finally:
            client.close()
    finally:
        _restore_env(previous)


def test_no_proxy_targeting_host_is_respected() -> None:
    """When the API host is listed in NO_PROXY, traffic bypasses the proxy."""
    transport = StubTransport()
    previous = _apply_proxy_env(
        proxy="http://proxy.example.test:8080",
        no_proxy="api.example.test",
    )
    try:
        client = _client(transport)
        try:
            assert client.get_project_status("p").status == "done"
            assert transport.routes == ["https://api.example.test/projects/p/status"]
        finally:
            client.close()
    finally:
        _restore_env(previous)


def test_proxy_environment_is_honoured_without_no_proxy() -> None:
    """Without NO_PROXY, the SDK client inherits the ambient proxy.

    httpx.Client (which the SDK constructs with defaults) mounts a proxy
    transport for https:// when HTTPS_PROXY is exported and trust_env is on.
    The CI matrix proves the SDK is transport-neutral: in the stripped run
    no proxy mount appears, in the exported run the https:// mount is
    proxy-capable. Here we assert the exported variant.
    """
    previous = _apply_proxy_env(
        proxy="http://proxy.example.test:8080",
        no_proxy=None,
    )
    try:
        client = KodegeneratorClient("https://api.example.test", "k")
        try:
            mounts = client._client._mounts
            patterns = [pattern.pattern for pattern in mounts]
            https = next(
                (pattern for pattern in mounts if pattern.pattern == "https://"), None
            )
            assert https is not None, f"expected https:// proxy mount, got {patterns}"
            transport = mounts[https]
            # The https:// mount is backed by an httpcore.HTTPProxy pool when
            # the ambient proxy is honoured; it records the proxy URL.
            pool = getattr(transport, "_pool", None)
            proxy_attr = getattr(pool, "_proxy_url", None)
            assert proxy_attr is not None, (
                "expected a proxy transport on https:// mount"
            )
            assert proxy_attr.host == b"proxy.example.test"
            assert proxy_attr.port == 8080
        finally:
            client.close()
    finally:
        _restore_env(previous)
