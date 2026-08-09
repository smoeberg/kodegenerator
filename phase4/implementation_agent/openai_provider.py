"""OpenAI Responses provider for bounded implementation patch candidates."""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from collections.abc import Callable, Mapping, Sequence

from .models import IMPLEMENTATION_ACTION, ImplementationRequest, PatchCandidate

OPENAI_IMPLEMENTATION_RESPONSES_URL = "https://api.openai.com/v1/responses"
_HTTP_MAX_RESPONSE_BYTES = 2 * 1024 * 1024


class OpenAIImplementationProviderError(RuntimeError):
    """Base error for the external implementation-model boundary."""


class OpenAIImplementationInputLimitError(OpenAIImplementationProviderError):
    """The complete bounded request exceeds the configured provider budget."""


class OpenAIImplementationResponseError(OpenAIImplementationProviderError):
    """The provider returned an incomplete, refused, or malformed response."""


ResponsesTransport = Callable[
    [str, Mapping[str, str], bytes, float], Mapping[str, object]
]


class OpenAIImplementationProvider:
    """Ask one fixed OpenAI model for a unified-diff patch candidate only."""

    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        max_input_bytes: int = 512 * 1024,
        max_output_bytes: int = 512 * 1024,
        timeout_seconds: float = 120.0,
        transport: ResponsesTransport | None = None,
    ) -> None:
        if (
            not isinstance(api_key, str)
            or not api_key.strip()
            or api_key != api_key.strip()
            or any(character in api_key for character in "\r\n")
        ):
            raise ValueError("api_key must be a canonical non-empty string")
        if not isinstance(model, str) or not model.strip():
            raise ValueError("model must be a non-empty string")
        if type(max_input_bytes) is not int or max_input_bytes < 1:
            raise ValueError("max_input_bytes must be a positive integer")
        if type(max_output_bytes) is not int or max_output_bytes < 1:
            raise ValueError("max_output_bytes must be a positive integer")
        if not isinstance(timeout_seconds, (int, float)) or timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        self._api_key = api_key
        self._model = model.strip()
        self._max_input_bytes = max_input_bytes
        self._max_output_bytes = max_output_bytes
        self._timeout_seconds = float(timeout_seconds)
        self._transport = transport or _http_transport

    @property
    def provider_id(self) -> str:
        return f"openai.responses:{self._model}"

    def propose_patch(self, request: ImplementationRequest) -> PatchCandidate:
        prompt = _implementation_prompt(request)
        prompt_bytes = prompt.encode("utf-8")
        if len(prompt_bytes) > self._max_input_bytes:
            raise OpenAIImplementationInputLimitError(
                "complete implementation prompt exceeds max_input_bytes; "
                "no context was sent"
            )
        body = json.dumps(
            {
                "model": self._model,
                "store": False,
                "instructions": _SYSTEM_INSTRUCTIONS,
                "input": [
                    {
                        "role": "user",
                        "content": [{"type": "input_text", "text": prompt}],
                    }
                ],
                "text": {
                    "format": {
                        "type": "json_schema",
                        "name": "dor_implementation_patch_candidate",
                        "strict": True,
                        "schema": _PATCH_CANDIDATE_SCHEMA,
                    }
                },
            },
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode("utf-8")
        response = self._transport(
            OPENAI_IMPLEMENTATION_RESPONSES_URL,
            {
                "Authorization": f"Bearer {self._api_key}",
                "Content-Type": "application/json",
                "User-Agent": "dor-implementation-agent/1.0",
            },
            body,
            self._timeout_seconds,
        )
        output_text = _response_output_text(response)
        if len(output_text.encode("utf-8")) > self._max_output_bytes:
            raise OpenAIImplementationResponseError(
                "OpenAI response exceeds max_output_bytes"
            )
        try:
            payload = json.loads(output_text)
        except json.JSONDecodeError as exc:
            raise OpenAIImplementationResponseError(
                "OpenAI response output is not valid JSON"
            ) from exc
        if not isinstance(payload, Mapping) or set(payload) != {"unified_diff"}:
            raise OpenAIImplementationResponseError(
                "OpenAI response does not match the strict patch schema"
            )
        unified_diff = payload["unified_diff"]
        if not isinstance(unified_diff, str) or not unified_diff.strip():
            raise OpenAIImplementationResponseError("OpenAI response contains no patch")
        return PatchCandidate(unified_diff=unified_diff)


def _http_transport(
    url: str,
    headers: Mapping[str, str],
    body: bytes,
    timeout_seconds: float,
) -> Mapping[str, object]:
    if url != OPENAI_IMPLEMENTATION_RESPONSES_URL:
        raise OpenAIImplementationProviderError(
            "OpenAI Responses API endpoint is not allowed"
        )
    request = urllib.request.Request(
        url,
        data=body,
        headers=dict(headers),
        method="POST",
    )
    try:
        with urllib.request.urlopen(  # nosec B310
            request, timeout=timeout_seconds
        ) as response:
            raw = response.read(_HTTP_MAX_RESPONSE_BYTES + 1)
    except urllib.error.HTTPError as exc:
        raise OpenAIImplementationProviderError(
            f"OpenAI Responses API returned HTTP {exc.code}"
        ) from exc
    except (urllib.error.URLError, TimeoutError) as exc:
        raise OpenAIImplementationProviderError(
            "OpenAI Responses API request failed"
        ) from exc
    if len(raw) > _HTTP_MAX_RESPONSE_BYTES:
        raise OpenAIImplementationResponseError(
            "OpenAI Responses API envelope exceeds the response limit"
        )
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise OpenAIImplementationResponseError(
            "OpenAI Responses API returned a malformed JSON envelope"
        ) from exc
    if not isinstance(payload, Mapping):
        raise OpenAIImplementationResponseError(
            "OpenAI Responses API envelope must be an object"
        )
    return payload


def _implementation_prompt(request: ImplementationRequest) -> str:
    payload = {
        "action": IMPLEMENTATION_ACTION,
        "repository": request.resource,
        "instruction": request.instruction,
        "allowed_paths": list(request.allowed_paths),
        "budget": {
            "max_files": request.budget.max_files,
            "max_changed_lines": request.budget.max_changed_lines,
        },
        "context_packet_id": request.context_packet_id,
        "context": [item.canonical() for item in request.context_packet.items],
    }
    return (
        "Produce one minimal Git unified text diff for the exact bounded request. "
        "Touch only allowed_paths and stay within both budgets. Do not include "
        "Markdown fences, prose, commands, renames, or binary changes. Return only "
        "the structured candidate.\n\n"
        + json.dumps(payload, sort_keys=True, ensure_ascii=False)
    )


def _response_output_text(response: Mapping[str, object]) -> str:
    status = response.get("status")
    if status != "completed":
        raise OpenAIImplementationResponseError(
            f"OpenAI response did not complete (status={status!r})"
        )
    direct = response.get("output_text")
    if isinstance(direct, str) and direct:
        return direct
    output = response.get("output")
    if not _is_sequence(output):
        raise OpenAIImplementationResponseError(
            "OpenAI response contains no output items"
        )
    texts: list[str] = []
    for item in output:
        if not isinstance(item, Mapping):
            continue
        content = item.get("content")
        if not _is_sequence(content):
            continue
        for part in content:
            if not isinstance(part, Mapping):
                continue
            if part.get("type") == "refusal":
                raise OpenAIImplementationResponseError(
                    "OpenAI model refused the implementation request"
                )
            if part.get("type") == "output_text" and isinstance(part.get("text"), str):
                texts.append(part["text"])
    if len(texts) != 1 or not texts[0]:
        raise OpenAIImplementationResponseError(
            "OpenAI response must contain exactly one structured output text"
        )
    return texts[0]


def _is_sequence(value: object) -> bool:
    return isinstance(value, Sequence) and not isinstance(
        value, (str, bytes, bytearray)
    )


_SYSTEM_INSTRUCTIONS = """You are a bounded DOR Implementation Agent provider.
You may propose one patch but cannot apply it, run commands, change authority,
expand scope, or declare success. Follow the supplied path and change budgets.
The surrounding DOR runtime independently validates every returned diff."""

_PATCH_CANDIDATE_SCHEMA = {
    "type": "object",
    "properties": {"unified_diff": {"type": "string"}},
    "required": ["unified_diff"],
    "additionalProperties": False,
}
