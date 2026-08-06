"""Foundation hardening gates for the pre-Phase-3 runtime boundary."""

import importlib


def test_canonical_modules_import(monkeypatch):
    monkeypatch.setenv("DOR_JWT_SECRET_KEY", "test-only-secret")

    modules = (
        "runtime.core",
        "runtime.commands",
        "infrastructure.persistence.models",
        "infrastructure.persistence.repositories",
        "infrastructure.persistence.uow",
        "api.dependencies",
        "api.auth",
        "seed_data",
        "ai.client",
    )
    for module_name in modules:
        importlib.import_module(module_name)


def test_legacy_persistence_boundary_is_not_importable():
    try:
        importlib.import_module("infrastructure.database.dor_runtime_db")
    except ModuleNotFoundError:
        return
    raise AssertionError("legacy DORRuntimeDB persistence boundary still exists")
