"""OpenAI Responses API provider for governed project-audit candidates.

The provider has no authority and performs no repository I/O.  It receives the
already bounded evidence bundle, requests a strict JSON candidate, and converts
that untrusted payload into the existing contract types.  The AI-4 adapter then
performs the authoritative evidence validation.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from collections.abc import Callable, Mapping, Sequence
from typing import Any

from .models import (
    AuditFindingCandidate,
    AuditRecommendation,
    EvidenceAssertion,
    EvidencePredicate,
    FindingClassification,
    FindingSeverity,
    MaturityAssessment,
    MaturityLevel,
    MaturityStatus,
    ProjectAuditCandidate,
    ProjectAuditRequest,
)

OPENAI_RESPONSES_URL = "https://api.openai.com/v1/responses"


class OpenAIProjectAuditProviderError(RuntimeError):
    """Base error for the external model boundary."""


class OpenAIProjectAuditInputLimitError(OpenAIProjectAuditProviderError):
    """The complete evidence prompt exceeds the explicit provider budget."""


class OpenAIProjectAuditResponseError(OpenAIProjectAuditProviderError):
    """The provider returned an incomplete, refused, or malformed response."""


ResponsesTransport = Callable[
    [str, Mapping[str, str], bytes, float], Mapping[str, object]
]


class OpenAIProjectAuditProvider:
    """Use OpenAI Structured Outputs to propose a project-audit candidate.

    Selecting this provider explicitly sends the bounded repository evidence to
    OpenAI. API keys remain in the Authorization header and are never added to
    prompts, identities, reports, or exception messages.
    """

    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        max_input_bytes: int = 2 * 1024 * 1024,
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
        if not isinstance(timeout_seconds, (int, float)) or timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        self._api_key = api_key
        self._model = model.strip()
        self._max_input_bytes = max_input_bytes
        self._timeout_seconds = float(timeout_seconds)
        self._transport = transport or _http_transport

    @property
    def provider_id(self) -> str:
        return f"openai.responses:{self._model}"

    def audit_project(self, request: ProjectAuditRequest) -> ProjectAuditCandidate:
        prompt = _audit_prompt(request)
        prompt_bytes = prompt.encode("utf-8")
        if len(prompt_bytes) > self._max_input_bytes:
            raise OpenAIProjectAuditInputLimitError(
                "complete evidence prompt exceeds max_input_bytes; no evidence was sent"
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
                        "name": "dor_project_audit_candidate",
                        "strict": True,
                        "schema": PROJECT_AUDIT_CANDIDATE_SCHEMA,
                    }
                },
            },
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode("utf-8")
        response = self._transport(
            OPENAI_RESPONSES_URL,
            {
                "Authorization": f"Bearer {self._api_key}",
                "Content-Type": "application/json",
                "User-Agent": "dor-project-audit/1.0",
            },
            body,
            self._timeout_seconds,
        )
        output_text = _response_output_text(response)
        try:
            payload = json.loads(output_text)
        except json.JSONDecodeError as exc:
            raise OpenAIProjectAuditResponseError(
                "OpenAI response output is not valid JSON"
            ) from exc
        return _candidate_from_mapping(payload)


def _http_transport(
    url: str,
    headers: Mapping[str, str],
    body: bytes,
    timeout_seconds: float,
) -> Mapping[str, object]:
    request = urllib.request.Request(
        url,
        data=body,
        headers=dict(headers),
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
            raw = response.read()
    except urllib.error.HTTPError as exc:
        raise OpenAIProjectAuditProviderError(
            f"OpenAI Responses API returned HTTP {exc.code}"
        ) from exc
    except (urllib.error.URLError, TimeoutError) as exc:
        raise OpenAIProjectAuditProviderError(
            "OpenAI Responses API request failed"
        ) from exc
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise OpenAIProjectAuditResponseError(
            "OpenAI Responses API returned a malformed JSON envelope"
        ) from exc
    if not isinstance(payload, Mapping):
        raise OpenAIProjectAuditResponseError(
            "OpenAI Responses API envelope must be an object"
        )
    return payload


def _audit_prompt(request: ProjectAuditRequest) -> str:
    context_items = [item.canonical() for item in request.context_packet.items]
    artifacts = [
        {
            "path": item.path,
            "kind": item.kind.value,
            "sha256": item.sha256,
            "byte_count": item.byte_count,
            "content": item.content,
        }
        for item in request.evidence_bundle.artifacts
    ]
    evidence = {
        "repository": request.resource,
        "commit_sha": request.evidence_bundle.commit_sha,
        "manifest_id": request.evidence_bundle.manifest.manifest_id,
        "bundle_id": request.evidence_bundle.bundle_id,
        "objectives": list(request.objectives),
        "target_maturity": request.target_maturity.value,
        "context": context_items,
        "artifacts": artifacts,
    }
    return (
        "Audit this exact, complete repository evidence bundle. Return only the "
        "structured candidate. Every evidence and counterevidence assertion must "
        "be a true machine-checkable observation in the supplied bundle. Use FACT "
        "only for directly established claims; use INFERENCE for reasoned cross-file "
        "conclusions and UNKNOWN when evidence is insufficient. Do not claim PASS, "
        "FAIL, authority, execution, or production readiness without evidence.\n\n"
        + json.dumps(evidence, sort_keys=True, ensure_ascii=False)
    )


def _response_output_text(response: Mapping[str, object]) -> str:
    status = response.get("status")
    if status != "completed":
        raise OpenAIProjectAuditResponseError(
            f"OpenAI response did not complete (status={status!r})"
        )

    direct = response.get("output_text")
    if isinstance(direct, str) and direct:
        return direct

    output = response.get("output")
    if not _is_sequence(output):
        raise OpenAIProjectAuditResponseError(
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
                raise OpenAIProjectAuditResponseError(
                    "OpenAI model refused the project audit request"
                )
            if part.get("type") == "output_text" and isinstance(part.get("text"), str):
                texts.append(part["text"])
    if len(texts) != 1 or not texts[0]:
        raise OpenAIProjectAuditResponseError(
            "OpenAI response must contain exactly one structured output text"
        )
    return texts[0]


def _candidate_from_mapping(value: object) -> ProjectAuditCandidate:
    root = _exact_mapping(
        value, {"findings", "maturity", "recommendation"}, "candidate"
    )
    findings = tuple(
        _finding_from_mapping(item)
        for item in _sequence(root["findings"], "candidate.findings")
    )
    maturity = tuple(
        _maturity_from_mapping(item)
        for item in _sequence(root["maturity"], "candidate.maturity")
    )
    try:
        recommendation = AuditRecommendation(
            _string(root["recommendation"], "candidate.recommendation")
        )
        return ProjectAuditCandidate(findings, maturity, recommendation)
    except (TypeError, ValueError) as exc:
        raise OpenAIProjectAuditResponseError(
            f"invalid project-audit candidate: {exc}"
        ) from exc


def _finding_from_mapping(value: object) -> AuditFindingCandidate:
    item = _exact_mapping(
        value,
        {
            "key",
            "title",
            "classification",
            "severity",
            "summary",
            "rationale",
            "evidence",
            "counterevidence",
            "consequences",
        },
        "finding",
    )
    try:
        return AuditFindingCandidate(
            key=_string(item["key"], "finding.key"),
            title=_string(item["title"], "finding.title"),
            classification=FindingClassification(
                _string(item["classification"], "finding.classification")
            ),
            severity=FindingSeverity(_string(item["severity"], "finding.severity")),
            summary=_string(item["summary"], "finding.summary"),
            rationale=_string(item["rationale"], "finding.rationale"),
            evidence=tuple(
                _assertion_from_mapping(assertion)
                for assertion in _sequence(item["evidence"], "finding.evidence")
            ),
            counterevidence=tuple(
                _assertion_from_mapping(assertion)
                for assertion in _sequence(
                    item["counterevidence"], "finding.counterevidence"
                )
            ),
            consequences=tuple(
                _string(consequence, "finding.consequences[]")
                for consequence in _sequence(
                    item["consequences"], "finding.consequences"
                )
            ),
        )
    except (TypeError, ValueError) as exc:
        raise OpenAIProjectAuditResponseError(
            f"invalid project-audit finding: {exc}"
        ) from exc


def _assertion_from_mapping(value: object) -> EvidenceAssertion:
    item = _exact_mapping(value, {"path", "predicate", "expected"}, "assertion")
    expected = item["expected"]
    if expected is not None:
        expected = _string(expected, "assertion.expected")
    try:
        return EvidenceAssertion(
            path=_string(item["path"], "assertion.path"),
            predicate=EvidencePredicate(
                _string(item["predicate"], "assertion.predicate")
            ),
            expected=expected,
        )
    except (TypeError, ValueError) as exc:
        raise OpenAIProjectAuditResponseError(
            f"invalid project-audit assertion: {exc}"
        ) from exc


def _maturity_from_mapping(value: object) -> MaturityAssessment:
    item = _exact_mapping(
        value,
        {"level", "status", "rationale", "finding_keys"},
        "maturity",
    )
    try:
        return MaturityAssessment(
            level=MaturityLevel(_string(item["level"], "maturity.level")),
            status=MaturityStatus(_string(item["status"], "maturity.status")),
            rationale=_string(item["rationale"], "maturity.rationale"),
            finding_keys=tuple(
                _string(key, "maturity.finding_keys[]")
                for key in _sequence(item["finding_keys"], "maturity.finding_keys")
            ),
        )
    except (TypeError, ValueError) as exc:
        raise OpenAIProjectAuditResponseError(
            f"invalid project-audit maturity assessment: {exc}"
        ) from exc


def _exact_mapping(
    value: object,
    keys: set[str],
    name: str,
) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise OpenAIProjectAuditResponseError(f"{name} must be an object")
    actual = set(value)
    if actual != keys:
        raise OpenAIProjectAuditResponseError(
            f"{name} keys do not match the strict schema"
        )
    return value


def _sequence(value: object, name: str) -> Sequence[object]:
    if not _is_sequence(value):
        raise OpenAIProjectAuditResponseError(f"{name} must be an array")
    return value


def _is_sequence(value: object) -> bool:
    return isinstance(value, Sequence) and not isinstance(
        value, (str, bytes, bytearray)
    )


def _string(value: object, name: str) -> str:
    if not isinstance(value, str):
        raise OpenAIProjectAuditResponseError(f"{name} must be a string")
    return value


_ASSERTION_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "path": {"type": "string"},
        "predicate": {
            "type": "string",
            "enum": [item.value for item in EvidencePredicate],
        },
        "expected": {"type": ["string", "null"]},
    },
    "required": ["path", "predicate", "expected"],
    "additionalProperties": False,
}

PROJECT_AUDIT_CANDIDATE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "findings": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "key": {"type": "string"},
                    "title": {"type": "string"},
                    "classification": {
                        "type": "string",
                        "enum": [item.value for item in FindingClassification],
                    },
                    "severity": {
                        "type": "string",
                        "enum": [item.value for item in FindingSeverity],
                    },
                    "summary": {"type": "string"},
                    "rationale": {"type": "string"},
                    "evidence": {"type": "array", "items": _ASSERTION_SCHEMA},
                    "counterevidence": {
                        "type": "array",
                        "items": _ASSERTION_SCHEMA,
                    },
                    "consequences": {"type": "array", "items": {"type": "string"}},
                },
                "required": [
                    "key",
                    "title",
                    "classification",
                    "severity",
                    "summary",
                    "rationale",
                    "evidence",
                    "counterevidence",
                    "consequences",
                ],
                "additionalProperties": False,
            },
        },
        "maturity": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "level": {
                        "type": "string",
                        "enum": [item.value for item in MaturityLevel],
                    },
                    "status": {
                        "type": "string",
                        "enum": [item.value for item in MaturityStatus],
                    },
                    "rationale": {"type": "string"},
                    "finding_keys": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                },
                "required": ["level", "status", "rationale", "finding_keys"],
                "additionalProperties": False,
            },
        },
        "recommendation": {
            "type": "string",
            "enum": [item.value for item in AuditRecommendation],
        },
    },
    "required": ["findings", "maturity", "recommendation"],
    "additionalProperties": False,
}

_SYSTEM_INSTRUCTIONS = """You are DOR's read-only Project Audit Agent.
Assess the whole supplied revision, challenge unsupported claims, distinguish
FACT from INFERENCE and UNKNOWN, and focus on cross-project coherence rather
than package-local style. Every evidence assertion you return must be true for
the supplied artifacts. Counterevidence is also an observed assertion, never a
hypothetical. You are advisory only: never claim authority, PASS, or FAIL."""
