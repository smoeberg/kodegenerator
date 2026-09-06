"""Trust-boundary tests for governed repository checkout discovery."""
from __future__ import annotations

import json

import pytest

from dashboard.repository_checkout_catalog import (
    RepositoryCheckoutCatalog,
    RepositoryCheckoutCatalogError,
    discover_repositories_for_organization,
    discover_repository_checkout,
)


def _root(tmp_path):
    root = tmp_path / "checkouts"
    root.mkdir()
    return root


def test_catalog_discovers_exact_repositories_per_organization(tmp_path) -> None:
    root = _root(tmp_path)
    (root / "repo-b").mkdir()
    (root / "repo-a").mkdir()
    catalog = RepositoryCheckoutCatalog.from_payload(
        root=root,
        payload={
            "version": 1,
            "repositories": [
                {
                    "organization_id": "org-a",
                    "repository": "repository:example/repo-b",
                    "checkout": "repo-b",
                },
                {
                    "organization_id": "org-a",
                    "repository": "repository:example/repo-a",
                    "checkout": "repo-a",
                },
                {
                    "organization_id": "org-b",
                    "repository": "repository:example/repo-a",
                    "checkout": "repo-a",
                },
            ],
        },
    )

    assert catalog.repositories_for("org-a") == (
        "repository:example/repo-a",
        "repository:example/repo-b",
    )
    binding = catalog.binding_for(
        organization_id="org-a",
        repository="repository:example/repo-b",
    )
    assert binding.root == (root / "repo-b").resolve()


def test_catalog_rejects_duplicate_org_repository_identity(tmp_path) -> None:
    root = _root(tmp_path)
    (root / "repo").mkdir()
    payload = {
        "version": 1,
        "repositories": [
            {
                "organization_id": "org-a",
                "repository": "repository:example/repo",
                "checkout": "repo",
            },
            {
                "organization_id": "org-a",
                "repository": "repository:example/repo",
                "checkout": "repo",
            },
        ],
    }

    with pytest.raises(RepositoryCheckoutCatalogError, match="dublet"):
        RepositoryCheckoutCatalog.from_payload(root=root, payload=payload)


def test_catalog_rejects_wildcard_repository_identity(tmp_path) -> None:
    root = _root(tmp_path)
    (root / "repo").mkdir()

    with pytest.raises(RepositoryCheckoutCatalogError, match="wildcards"):
        RepositoryCheckoutCatalog.from_payload(
            root=root,
            payload={
                "version": 1,
                "repositories": [
                    {
                        "organization_id": "org-a",
                        "repository": "repository:example/*",
                        "checkout": "repo",
                    }
                ],
            },
        )


def test_catalog_rejects_checkout_traversal_and_absolute_paths(tmp_path) -> None:
    root = _root(tmp_path)
    outside = tmp_path / "outside"
    outside.mkdir()

    for checkout in ("../outside", str(outside)):
        with pytest.raises(RepositoryCheckoutCatalogError, match="relativ sti"):
            RepositoryCheckoutCatalog.from_payload(
                root=root,
                payload={
                    "version": 1,
                    "repositories": [
                        {
                            "organization_id": "org-a",
                            "repository": "repository:example/repo",
                            "checkout": checkout,
                        }
                    ],
                },
            )


def test_catalog_rejects_symlink_escape(tmp_path) -> None:
    root = _root(tmp_path)
    outside = tmp_path / "outside"
    outside.mkdir()
    (root / "escape").symlink_to(outside, target_is_directory=True)

    with pytest.raises(RepositoryCheckoutCatalogError, match="escape"):
        RepositoryCheckoutCatalog.from_payload(
            root=root,
            payload={
                "version": 1,
                "repositories": [
                    {
                        "organization_id": "org-a",
                        "repository": "repository:example/repo",
                        "checkout": "escape",
                    }
                ],
            },
        )


def test_catalog_environment_discovery_resolves_same_exact_binding(tmp_path) -> None:
    root = _root(tmp_path)
    checkout = root / "repo"
    checkout.mkdir()
    catalog_file = tmp_path / "catalog.json"
    catalog_file.write_text(
        json.dumps(
            {
                "version": 1,
                "repositories": [
                    {
                        "organization_id": "org-a",
                        "repository": "repository:example/repo",
                        "checkout": "repo",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    environment = {
        "DOR_PROJECT_AUDIT_CHECKOUTS_ROOT": str(root),
        "DOR_PROJECT_AUDIT_CHECKOUT_CATALOG": str(catalog_file),
    }

    assert discover_repositories_for_organization("org-a", environment) == (
        "repository:example/repo",
    )
    binding = discover_repository_checkout(
        organization_id="org-a",
        repository="repository:example/repo",
        environment=environment,
    )
    assert binding.root == checkout.resolve()


def test_catalog_partial_configuration_fails_closed(tmp_path) -> None:
    root = _root(tmp_path)

    with pytest.raises(RepositoryCheckoutCatalogError, match="delvist"):
        discover_repositories_for_organization(
            "org-a",
            {"DOR_PROJECT_AUDIT_CHECKOUTS_ROOT": str(root)},
        )


def test_discovery_preserves_legacy_single_checkout_fallback(tmp_path) -> None:
    environment = {
        "DOR_PROJECT_AUDIT_ORGANIZATION_ID": "org-a",
        "DOR_PROJECT_AUDIT_REPOSITORY": "repository:example/repo",
        "DOR_PROJECT_AUDIT_CHECKOUT_ROOT": str(tmp_path),
    }

    assert discover_repositories_for_organization("org-a", environment) == (
        "repository:example/repo",
    )
    binding = discover_repository_checkout(
        organization_id="org-a",
        repository="repository:example/repo",
        environment=environment,
    )
    assert binding.root == tmp_path.resolve()


def test_discovery_returns_none_when_no_repository_source_is_configured() -> None:
    assert discover_repositories_for_organization("org-a", {}) is None
