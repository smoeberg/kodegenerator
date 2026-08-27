import json

import pytest

from services.llm_adapters import LLMResponse, MockLLMAdapter, SchemaValidationError
from services.llm_router import LLMRouter


def test_mock_adapter_returns_normalized_response_and_tokens():
    response = MockLLMAdapter().generate("hello world")
    assert isinstance(response, LLMResponse)
    assert response.text == "mock response"
    assert response.prompt_tokens == 2
    assert response.completion_tokens == 2


def test_json_mode_recovers_valid_json():
    response = MockLLMAdapter('{"answer":"ok"}').generate("p", {"type": "object", "required": ["answer"]})
    assert json.loads(response.text) == {"answer": "ok"}


def test_json_mode_is_fail_safe_for_invalid_payload():
    with pytest.raises(SchemaValidationError):
        MockLLMAdapter("not-json").generate("p", {"type": "object", "required": ["answer"]})


def test_router_selects_provider_and_fallback():
    selected = MockLLMAdapter("selected", model="x")
    fallback = MockLLMAdapter("fallback")
    router = LLMRouter({"mock": selected}, fallback)
    assert router.generate("mock", "p").text == "selected"
    assert router.generate("missing", "p").text == "fallback"


def test_stream_exposes_response_as_chunks():
    adapter = MockLLMAdapter("streamed")
    assert list(adapter.stream("p")) == ["streamed"]
