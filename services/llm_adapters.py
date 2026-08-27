"""Provider-neutral LLM adapters with retries, streaming and JSON recovery."""
from __future__ import annotations

import json
import time
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from typing import Any, Protocol
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from jsonschema import SchemaError, ValidationError, validators
from pydantic import BaseModel
from pydantic import ValidationError as PydanticValidationError

from .secure_http import validate_http_url


class SchemaValidationError(ValueError):
    """An LLM response did not satisfy its mandatory response schema."""


@dataclass(frozen=True)
class LLMResponse:
    """Normalized response returned by every adapter."""
    text: str
    model: str
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    raw: Any = None
    streamed: bool = False


class CostSink(Protocol):
    """Minimal optional CostOptimizer-compatible protocol."""
    def record_usage(self, provider: str, model: str, prompt_tokens: int, completion_tokens: int) -> None: ...


class BaseLLMAdapter:
    """Base adapter implementing retries, rate-limit handling and JSON recovery."""
    provider = "unknown"

    def __init__(self, model: str, *, max_retries: int = 3, backoff_base: float = 0.25, cost_optimizer: CostSink | None = None) -> None:
        self.model = model
        self.max_retries = max(0, max_retries)
        self.backoff_base = max(0.0, backoff_base)
        self.cost_optimizer = cost_optimizer

    def generate(self, prompt: str, schema: Mapping[str, Any] | type[BaseModel] | BaseModel | None = None, temperature: float = 0.2) -> LLMResponse:
        """Generate a normalized response, retrying transient failures."""
        for attempt in range(self.max_retries + 1):
            try:
                response = self._generate(prompt, schema, temperature)
                self._record_cost(response)
                if schema is not None:
                    response = self._recover_json(response, schema)
                return response
            except Exception as exc:
                if attempt >= self.max_retries or not self._retryable(exc):
                    raise
                time.sleep(self.backoff_base * (2 ** attempt))
        raise RuntimeError("unreachable")

    def stream(self, prompt: str, schema: Mapping[str, Any] | type[BaseModel] | BaseModel | None = None, temperature: float = 0.2) -> Iterator[str]:
        """Yield generated text chunks; adapters may override for native streaming."""
        yield self.generate(prompt, schema, temperature).text

    def _generate(self, prompt: str, schema: Mapping[str, Any] | None, temperature: float) -> LLMResponse:
        raise NotImplementedError

    def _retryable(self, exc: Exception) -> bool:
        if isinstance(exc, HTTPError):
            return exc.code == 429 or 500 <= exc.code < 600
        return isinstance(exc, (TimeoutError, ConnectionError))

    def _record_cost(self, response: LLMResponse) -> None:
        if self.cost_optimizer is not None:
            self.cost_optimizer.record_usage(self.provider, response.model, response.prompt_tokens, response.completion_tokens)

    @staticmethod
    def _recover_json(response: LLMResponse, schema: Mapping[str, Any] | type[BaseModel] | BaseModel) -> LLMResponse:
        """Parse JSON safely and return a normalized JSON string; schema errors fail closed."""
        try:
            value = json.loads(response.text)
        except json.JSONDecodeError as exc:
            raise SchemaValidationError("LLM response is not valid JSON") from exc
        try:
            if isinstance(schema, BaseModel):
                validated = type(schema).model_validate(value).model_dump(mode="json")
            elif isinstance(schema, type) and issubclass(schema, BaseModel):
                validated = schema.model_validate(value).model_dump(mode="json")
            elif isinstance(schema, Mapping):
                validator_class = validators.validator_for(schema)
                validator_class.check_schema(schema)
                validator_class(schema).validate(value)
                validated = value
            else:
                raise TypeError("schema must be a JSON Schema mapping or Pydantic model")
        except (ValidationError, SchemaError, PydanticValidationError) as exc:
            raise SchemaValidationError("LLM response failed schema validation") from exc
        text = json.dumps(validated, separators=(",", ":"), sort_keys=True)
        return LLMResponse(text, response.model, response.prompt_tokens, response.completion_tokens, response.total_tokens, response.raw, response.streamed)


class OpenAIAdapter(BaseLLMAdapter):
    """OpenAI-compatible HTTP adapter using stdlib networking."""
    provider = "openai"

    def __init__(self, api_key: str, model: str = "gpt-4o-mini", *, base_url: str = "https://api.openai.com/v1", **kwargs: Any) -> None:
        super().__init__(model, **kwargs)
        self.api_key, self.base_url = api_key, validate_http_url(base_url).rstrip("/")

    def _generate(self, prompt: str, schema: Mapping[str, Any] | None, temperature: float) -> LLMResponse:
        payload: dict[str, Any] = {"model": self.model, "messages": [{"role": "user", "content": prompt}], "temperature": temperature}
        if schema is not None:
            payload["response_format"] = {"type": "json_object"}
        req = Request(validate_http_url(f"{self.base_url}/chat/completions"), json.dumps(payload).encode(), {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"})
        with urlopen(req, timeout=60) as result:  # nosec B310 - URL is explicitly restricted to HTTP(S).
            data = json.load(result)
        usage = data.get("usage", {})
        return LLMResponse(data["choices"][0]["message"]["content"], data.get("model", self.model), int(usage.get("prompt_tokens", 0)), int(usage.get("completion_tokens", 0)), int(usage.get("total_tokens", 0)), data)


class AnthropicAdapter(BaseLLMAdapter):
    """Anthropic Messages API adapter."""
    provider = "anthropic"

    def __init__(self, api_key: str, model: str = "claude-3-5-sonnet-latest", *, base_url: str = "https://api.anthropic.com/v1", **kwargs: Any) -> None:
        super().__init__(model, **kwargs)
        self.api_key, self.base_url = api_key, validate_http_url(base_url).rstrip("/")

    def _generate(self, prompt: str, schema: Mapping[str, Any] | None, temperature: float) -> LLMResponse:
        payload = {"model": self.model, "max_tokens": 4096, "messages": [{"role": "user", "content": prompt}], "temperature": temperature}
        req = Request(validate_http_url(f"{self.base_url}/messages"), json.dumps(payload).encode(), {"x-api-key": self.api_key, "anthropic-version": "2023-06-01", "Content-Type": "application/json"})
        with urlopen(req, timeout=60) as result:  # nosec B310 - URL is explicitly restricted to HTTP(S).
            data = json.load(result)
        usage = data.get("usage", {})
        text = "".join(block.get("text", "") for block in data.get("content", []) if block.get("type") == "text")
        return LLMResponse(text, data.get("model", self.model), int(usage.get("input_tokens", 0)), int(usage.get("output_tokens", 0)), int(usage.get("input_tokens", 0)) + int(usage.get("output_tokens", 0)), data)


class OllamaAdapter(BaseLLMAdapter):
    """Local Ollama HTTP adapter."""
    provider = "ollama"

    def __init__(self, model: str = "llama3.1", *, base_url: str = "http://localhost:11434", **kwargs: Any) -> None:
        super().__init__(model, **kwargs)
        self.base_url = validate_http_url(base_url).rstrip("/")

    def _generate(self, prompt: str, schema: Mapping[str, Any] | None, temperature: float) -> LLMResponse:
        payload = {"model": self.model, "prompt": prompt, "stream": False, "options": {"temperature": temperature}}
        req = Request(validate_http_url(f"{self.base_url}/api/generate"), json.dumps(payload).encode(), {"Content-Type": "application/json"})
        with urlopen(req, timeout=120) as result:  # nosec B310 - URL is explicitly restricted to HTTP(S).
            data = json.load(result)
        return LLMResponse(data.get("response", ""), data.get("model", self.model), int(data.get("prompt_eval_count", 0)), int(data.get("eval_count", 0)), int(data.get("prompt_eval_count", 0)) + int(data.get("eval_count", 0)), data)


class MockLLMAdapter(BaseLLMAdapter):
    """Deterministic adapter for tests and safe fallback operation."""
    provider = "mock"

    def __init__(self, response: str = "mock response", model: str = "mock", **kwargs: Any) -> None:
        super().__init__(model, **kwargs)
        self.response = response

    def _generate(self, prompt: str, schema: Mapping[str, Any] | None, temperature: float) -> LLMResponse:
        return LLMResponse(self.response, self.model, len(prompt.split()), len(self.response.split()), len(prompt.split()) + len(self.response.split()))
