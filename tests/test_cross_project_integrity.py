"""Cross-project integrity recovery gates."""

from __future__ import annotations

import importlib
import importlib.util
import json
import re
import sys
from pathlib import Path

import pytest
from cryptography.fernet import Fernet
from fastapi import FastAPI

from dashboard.governance_catalog import CREATE_EXAMPLES, RESOURCE_PATHS, resource_path
from monitoring import tracer as tracer_module
from runtime.model_registry import Model, ModelProvider, ModelRegistry
from services.runtime_configuration import (
    RuntimeConfigurationError,
    validate_runtime_configuration,
)

ROOT = Path(__file__).resolve().parents[1]


def _dashboard_environment() -> dict[str, str]:
    """Canonical hardened wiring for the dashboard runtime role."""
    database = "postgresql+psycopg://dor:secret@postgres:5432/dor"
    return {
        "ARTIFACT_BUCKET": "dor-artifacts",
        "ARTIFACT_STORE_URL": "http://minio:9000",
        "AWS_ACCESS_KEY_ID": "minio-user",
        "AWS_SECRET_ACCESS_KEY": "s" * 32,
        "DATABASE_URL": database,
        "DOR_ADMIN_ORGANIZATION_ID": "org-1",
        "DOR_ADMIN_PASSWORD": "a" * 32,
        "DOR_ADMIN_USERNAME": "admin",
        "DOR_API_BASE": "http://api:8000",
        "DOR_AUTHORITY_SIGNING_KEY": "h" * 32,
        "DOR_ENCRYPTION_KEY": Fernet.generate_key().decode("ascii"),
        "DOR_ENV": "demo",
        "DOR_IDENTITY_DATABASE_URL": database,
        "DOR_JWT_ACTIVE_KEY_ID": "key-1",
        "DOR_JWT_SIGNING_KEYS": json.dumps({"key-1": "j" * 32}),
        "DOR_PIPELINE_DATABASE_URL": database,
        "DOR_PIPELINE_STATE_ORGANIZATION_ID": "org-1",
        "DOR_QUEUE_BACKEND": "database",
        "DOR_RUNTIME_ROLE": "dashboard",
        "DOR_WORKER_CAPABILITIES": "pipeline.code,pipeline.tests",
        "DOR_WORKER_CREDENTIAL": "w" * 32,
        "DOR_WORKER_ORGANIZATION_ID": "org-1",
        "DOR_WORKER_SERVICE_ID": "factory-worker",
    }


def test_root_entrypoint_reexports_canonical_api(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DOR_JWT_SECRET_KEY", "test-only-secret")
    monkeypatch.delenv("OTEL_EXPORTER_OTLP_ENDPOINT", raising=False)
    sys.modules.pop("main", None)

    root_entrypoint = importlib.import_module("main")
    canonical_api = importlib.import_module("api.main")

    assert root_entrypoint.app is canonical_api.app
    assert callable(root_entrypoint.run)


def test_compose_binds_fail_closed_runtime_configuration() -> None:
    # Test canonical compose.yml configuration
    compose = (ROOT / "compose.yml").read_text(encoding="utf-8")

    assert "DOR_JWT_SECRET_KEY: ${DOR_JWT_SECRET_KEY:-}" in compose
    assert "DOR_JWT_SIGNING_KEYS: ${DOR_JWT_SIGNING_KEYS:?DOR_JWT_SIGNING_KEYS must be set}" in compose
    assert "DOR_JWT_ACTIVE_KEY_ID: ${DOR_JWT_ACTIVE_KEY_ID:?DOR_JWT_ACTIVE_KEY_ID must be set}" in compose
    # Either the legacy secret or the keyring is required by API startup; the
    # compose layer must forward both options without choosing an unsafe one.
    assert not re.search(r"^\s*-?\s*JWT_SECRET_KEY[=:]", compose, re.MULTILINE)
    assert "OTEL_EXPORTER_OTLP_ENDPOINT: http://otel-collector:4317" in compose


def test_dashboard_configuration_requires_explicit_secrets() -> None:
    environment = _dashboard_environment()
    del environment["DOR_ADMIN_PASSWORD"]

    with pytest.raises(RuntimeConfigurationError, match="DOR_ADMIN_PASSWORD"):
        validate_runtime_configuration(environment)

    environment = _dashboard_environment()
    del environment["DOR_ENCRYPTION_KEY"]

    with pytest.raises(RuntimeConfigurationError, match="DOR_ENCRYPTION_KEY"):
        validate_runtime_configuration(environment)


def test_dashboard_secret_key_validation_fails_closed() -> None:
    environment = _dashboard_environment()
    environment["DOR_ENCRYPTION_KEY"] = "not-fernet"

    with pytest.raises(RuntimeConfigurationError, match="valid Fernet key"):
        validate_runtime_configuration(environment)


def test_legacy_dashboard_surfaces_are_not_restored() -> None:
    assert importlib.util.find_spec("dashboard.catalog") is None
    assert importlib.util.find_spec("dashboard.security") is None


def test_dashboard_governance_catalog_is_internally_complete() -> None:
    assert RESOURCE_PATHS
    assert set(RESOURCE_PATHS) == set(CREATE_EXAMPLES)
    for resource, path in RESOURCE_PATHS.items():
        assert path.startswith("/api/v1/bot-governance/")
        assert resource_path(resource) == path

    with pytest.raises(ValueError, match="Unsupported"):
        resource_path("imaginary")


def test_model_registry_is_importable_and_keeps_credentials_out_of_metadata() -> None:
    registry = ModelRegistry()
    model = Model(
        id="provider:model-v1",
        name="Model v1",
        provider=ModelProvider.LOCAL,
        capabilities=("generate",),
        max_tokens=1024,
        quality_score=0.8,
        reliability=0.9,
        availability=1.0,
    )

    registry.add_model(model)

    assert registry.get_model(model.id) is model
    assert registry.get_models_by_provider(ModelProvider.LOCAL) == [model]
    assert "api_key" not in model.__dataclass_fields__


def test_recovery_does_not_restore_retired_domain_models() -> None:
    assert importlib.util.find_spec("domain.model") is None
    assert importlib.util.find_spec("domain.predefined_roles") is None
    assert "from domain.model import" not in (
        ROOT / "runtime" / "model_registry.py"
    ).read_text(encoding="utf-8")


def test_tracing_is_opt_in_validated_and_idempotent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: dict[str, object] = {}
    sentinel_tracer = object()

    class FakeProvider:
        def __init__(self, *, resource: object) -> None:
            calls["resource"] = resource

        def add_span_processor(self, processor: object) -> None:
            calls["processor"] = processor

        def get_tracer(self, name: str) -> object:
            calls["tracer_name"] = name
            return sentinel_tracer

        def shutdown(self) -> None:
            calls["shutdown"] = True

    class FakeExporter:
        def __init__(self, *, endpoint: str, insecure: bool) -> None:
            calls["endpoint"] = endpoint
            calls["insecure"] = insecure

    class FakeProcessor:
        def __init__(self, exporter: object) -> None:
            calls["exporter"] = exporter

    def instrument_app(app: FastAPI, *, tracer_provider: object) -> None:
        calls["app"] = app
        calls["provider"] = tracer_provider

    monkeypatch.setattr(tracer_module, "TracerProvider", FakeProvider)
    monkeypatch.setattr(tracer_module, "OTLPSpanExporter", FakeExporter)
    monkeypatch.setattr(tracer_module, "BatchSpanProcessor", FakeProcessor)
    monkeypatch.setattr(
        tracer_module.FastAPIInstrumentor, "instrument_app", instrument_app
    )

    app = FastAPI()
    configured = tracer_module.configure_tracing(
        app,
        endpoint="http://otel-collector:4317",
    )

    assert configured is sentinel_tracer
    assert (
        tracer_module.configure_tracing(app, endpoint="https://unused.example")
        is configured
    )
    assert calls["endpoint"] == "http://otel-collector:4317"
    assert calls["insecure"] is True
    assert calls["app"] is app

    with pytest.raises(ValueError, match="absolute http"):
        tracer_module.configure_tracing(FastAPI(), endpoint="collector:4317")


def test_ci_compiles_and_scans_cross_project_packages() -> None:
    workflow = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")

    assert "python -m compileall -q ." in workflow
    for package in ("dashboard", "phase4", "services"):
        assert package in workflow
