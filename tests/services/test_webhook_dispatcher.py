import asyncio, hashlib, hmac, json
from unittest.mock import patch
import pytest
from services.webhook_dispatcher import WebhookDispatcher

@pytest.mark.asyncio
async def test_successful_hmac_dispatch():
    requests = []
    def mock_post(url, body, signature):
        requests.append((body, signature))
        return 200

    d = WebhookDispatcher(timeout=1, base_delay=0)
    with patch.object(d, "_post", side_effect=mock_post):
        d.register("a", "http://example.com/webhook", b"secret", {"PROJECT_COMPLETED"})
        await d.publish("PROJECT_COMPLETED", {"id": "p1"})
        await d.flush()

    assert len(requests) == 1
    body, sig = requests[0]
    expected_sig = hmac.new(b"secret", body, hashlib.sha256).hexdigest()
    assert hmac.compare_digest(sig, expected_sig)
    assert json.loads(body)["event"] == "PROJECT_COMPLETED"

@pytest.mark.asyncio
async def test_retries_500_and_records_dead_letter():
    calls = []
    def mock_post(url, body, signature):
        calls.append(url)
        return 500

    d = WebhookDispatcher(max_retries=2, timeout=1, base_delay=0)
    with patch.object(d, "_post", side_effect=mock_post):
        d.register("a", "http://example.com/fail", b"s", {"TASK_FAILED_DLQ"})
        await d.publish("TASK_FAILED_DLQ", {})
        await d.flush()

    assert len(calls) == 3
    assert len(d.dead_letters()) == 1
    assert d.dead_letters()[0].attempts == 3

@pytest.mark.asyncio
async def test_webhook_failure_is_isolated():
    def mock_post(url, body, signature):
        raise ConnectionRefusedError("connection failed")

    d = WebhookDispatcher(max_retries=1, timeout=0.01, base_delay=0)
    with patch.object(d, "_post", side_effect=mock_post):
        d.register("bad", "http://example.com/bad", b"s", {"CIRCUIT_BREAKER_OPEN"})
        await d.publish("CIRCUIT_BREAKER_OPEN", {"x": 1})
        await d.flush()

    assert len(d.dead_letters()) == 1

@pytest.mark.asyncio
async def test_event_subscription_filters():
    calls = []
    def mock_post(url, body, signature):
        calls.append(url)
        return 200

    d = WebhookDispatcher(timeout=1)
    with patch.object(d, "_post", side_effect=mock_post):
        d.register("a", "http://example.com/sub", b"s", {"PROJECT_COMPLETED"})
        await d.publish("TASK_FAILED_DLQ", {})
        await d.flush()

    assert not calls
