"""Cross-project integrity recovery gates."""

from __future__ import annotations

import importlib
import importlib.util
import re
import sys
from pathlib import Path
from types import MappingProxyType

import pytest
from cryptography.fernet import Fernet
from fastapi import FastAPI

from dashboard.catalog import STANDARD_CAPABILITIES, STANDARD_ROLES
from dashboard.security import (
    DashboardConfigurationError,
    DashboardSecretError,
    admin_password,
    decrypt_secret,
    encrypt_secret,
)
from monitoring import tracer as tracer_module
from runtime.model_registry import Model, ModelProvider, ModelRegistry

ROOT = Path(__file__).resolve().parents[1]


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


def test_dashboard_configuration_requires_explicit_secrets(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("DOR_ADMIN_PASSWORD", raising=False)
    monkeypatch.delenv("DOR_ENCRYPTION_KEY", raising=False)

    with pytest.raises(DashboardConfigurationError, match="DOR_ADMIN_PASSWORD"):
        admin_password()
    with pytest.raises(DashboardConfigurationError, match="DOR_ENCRYPTION_KEY"):
        encrypt_secret("provider-secret")


def test_dashboard_secret_encryption_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DOR_ENCRYPTION_KEY", Fernet.generate_key().decode("ascii"))

    encrypted = encrypt_secret("provider-secret")
    assert encrypted != "provider-secret"
    assert decrypt_secret(encrypted) == "provider-secret"

    with pytest.raises(DashboardSecretError, match="integrity"):
        decrypt_secret(encrypted[:-2] + "aa")


def test_dashboard_role_catalog_is_internally_complete() -> None:
    capability_ids = {capability.id for capability in STANDARD_CAPABILITIES.values()}

    assert STANDARD_ROLES
    assert capability_ids
    assert all(
        set(role.capabilities) <= capability_ids for role in STANDARD_ROLES.values()
    )
    mapping_proxy_type = type(MappingProxyType({}))
    assert all(
        isinstance(role.authority, mapping_proxy_type)
        for role in STANDARD_ROLES.values()
    )


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
