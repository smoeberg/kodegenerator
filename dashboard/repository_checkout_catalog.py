"""Server-owned repository discovery and read-only checkout bindings for GUI flows."""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping


_CATALOG_ROOT_ENV = "DOR_PROJECT_AUDIT_CHECKOUTS_ROOT"
_CATALOG_FILE_ENV = "DOR_PROJECT_AUDIT_CHECKOUT_CATALOG"
_LEGACY_ORGANIZATION_ENV = "DOR_PROJECT_AUDIT_ORGANIZATION_ID"
_LEGACY_REPOSITORY_ENV = "DOR_PROJECT_AUDIT_REPOSITORY"
_LEGACY_ROOT_ENV = "DOR_PROJECT_AUDIT_CHECKOUT_ROOT"
_AUTHORITY_GLOB_CHARS = frozenset("*?[")


class RepositoryCheckoutCatalogError(RuntimeError):
    """The server-owned repository checkout catalog is invalid or incomplete."""


@dataclass(frozen=True)
class RepositoryCheckoutBinding:
    """Exact organization + repository binding to one trusted checkout root."""

    organization_id: str
    repository: str
    root: Path

    def root_for(
        self,
        intent: object | None = None,
        *,
        organization_id: str | None = None,
        repository: str | None = None,
    ) -> Path:
        """Return the bound root after exact identity matching.

        ``intent`` is accepted as a compatibility shim for the Project Audit GUI
        binding introduced before the shared checkout catalog existed.
        """
        if intent is not None:
            if organization_id is not None or repository is not None:
                raise RepositoryCheckoutCatalogError(
                    "root_for accepterer enten intent eller explicit identity, ikke begge"
                )
            organization_id = getattr(intent, "organization_id", None)
            repository = getattr(intent, "source_repository", None)
        if organization_id != self.organization_id:
            raise RepositoryCheckoutCatalogError(
                "Onboarding-intentets organisation matcher ikke "
                "checkout-bindingens organisation"
            )
        if repository != self.repository:
            raise RepositoryCheckoutCatalogError(
                "Onboarding-intentets repository har ingen konfigureret audit-checkout"
            )
        return self.root.resolve()

    @classmethod
    def from_environment(
        cls,
        environment: Mapping[str, str] | None = None,
    ) -> "RepositoryCheckoutBinding":
        """Compatibility alias for the original single-checkout configuration."""
        return cls.from_legacy_environment(environment)

    @classmethod
    def from_legacy_environment(
        cls,
        environment: Mapping[str, str] | None = None,
    ) -> "RepositoryCheckoutBinding":
        """Load the v1 single-checkout configuration for backwards compatibility."""
        values = os.environ if environment is None else environment
        organization_id = values.get(_LEGACY_ORGANIZATION_ENV, "").strip()
        repository = values.get(_LEGACY_REPOSITORY_ENV, "").strip()
        root_value = values.get(_LEGACY_ROOT_ENV, "").strip()
        missing = [
            name
            for name, value in (
                (_LEGACY_ORGANIZATION_ENV, organization_id),
                (_LEGACY_REPOSITORY_ENV, repository),
                (_LEGACY_ROOT_ENV, root_value),
            )
            if not value
        ]
        if missing:
            raise RepositoryCheckoutCatalogError(
                "Project Audit checkout er ikke konfigureret: " + ", ".join(missing)
            )
        _validate_exact_text(organization_id, _LEGACY_ORGANIZATION_ENV)
        _validate_repository(repository, _LEGACY_REPOSITORY_ENV)
        root = _validate_absolute_directory(Path(root_value), _LEGACY_ROOT_ENV)
        return cls(
            organization_id=organization_id,
            repository=repository,
            root=root,
        )


@dataclass(frozen=True)
class RepositoryCheckoutCatalog:
    """Validated catalog of exact repository identities under one trusted root."""

    root: Path
    bindings: tuple[RepositoryCheckoutBinding, ...]

    @classmethod
    def from_environment(
        cls,
        environment: Mapping[str, str] | None = None,
    ) -> "RepositoryCheckoutCatalog":
        values = os.environ if environment is None else environment
        root_value = values.get(_CATALOG_ROOT_ENV, "").strip()
        catalog_value = values.get(_CATALOG_FILE_ENV, "").strip()
        if not root_value and not catalog_value:
            raise RepositoryCheckoutCatalogError(
                "Repository checkout-katalog er ikke konfigureret"
            )
        if not root_value or not catalog_value:
            missing = _CATALOG_ROOT_ENV if not root_value else _CATALOG_FILE_ENV
            raise RepositoryCheckoutCatalogError(
                f"Repository checkout-katalog er delvist konfigureret; {missing} mangler"
            )
        root = _validate_absolute_directory(Path(root_value), _CATALOG_ROOT_ENV)
        catalog_file = Path(catalog_value)
        if not catalog_file.is_absolute():
            raise RepositoryCheckoutCatalogError(
                f"{_CATALOG_FILE_ENV} skal være en absolut server-side sti"
            )
        if not catalog_file.is_file():
            raise RepositoryCheckoutCatalogError(
                "Repository checkout-katalogfilen findes ikke"
            )
        try:
            payload = json.loads(catalog_file.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise RepositoryCheckoutCatalogError(
                "Repository checkout-kataloget er ikke gyldig UTF-8 JSON"
            ) from exc
        return cls.from_payload(root=root, payload=payload)

    @classmethod
    def from_payload(
        cls,
        *,
        root: Path,
        payload: Any,
    ) -> "RepositoryCheckoutCatalog":
        trusted_root = _validate_absolute_directory(root, _CATALOG_ROOT_ENV)
        if not isinstance(payload, Mapping):
            raise RepositoryCheckoutCatalogError(
                "Repository checkout-kataloget skal være et JSON-object"
            )
        if payload.get("version") != 1:
            raise RepositoryCheckoutCatalogError(
                "Repository checkout-kataloget skal have version 1"
            )
        raw_repositories = payload.get("repositories")
        if not isinstance(raw_repositories, list):
            raise RepositoryCheckoutCatalogError(
                "Repository checkout-katalogets repositories skal være en liste"
            )

        bindings: list[RepositoryCheckoutBinding] = []
        identities: set[tuple[str, str]] = set()
        for index, raw in enumerate(raw_repositories):
            if not isinstance(raw, Mapping):
                raise RepositoryCheckoutCatalogError(
                    f"Repository checkout-katalogpost {index} skal være et object"
                )
            organization_id = _required_text(
                raw.get("organization_id"),
                f"repositories[{index}].organization_id",
            )
            repository = _required_text(
                raw.get("repository"),
                f"repositories[{index}].repository",
            )
            checkout = _required_text(
                raw.get("checkout"),
                f"repositories[{index}].checkout",
            )
            _validate_repository(
                repository,
                f"repositories[{index}].repository",
            )
            identity = (organization_id, repository)
            if identity in identities:
                raise RepositoryCheckoutCatalogError(
                    "Repository checkout-kataloget indeholder en dublet for "
                    f"{organization_id} / {repository}"
                )
            identities.add(identity)
            checkout_root = _resolve_catalog_checkout(
                trusted_root,
                checkout,
                field_name=f"repositories[{index}].checkout",
            )
            bindings.append(
                RepositoryCheckoutBinding(
                    organization_id=organization_id,
                    repository=repository,
                    root=checkout_root,
                )
            )

        return cls(
            root=trusted_root,
            bindings=tuple(
                sorted(
                    bindings,
                    key=lambda item: (item.organization_id, item.repository),
                )
            ),
        )

    def repositories_for(self, organization_id: str) -> tuple[str, ...]:
        _validate_exact_text(organization_id, "organization_id")
        return tuple(
            binding.repository
            for binding in self.bindings
            if binding.organization_id == organization_id
        )

    def binding_for(
        self,
        *,
        organization_id: str,
        repository: str,
    ) -> RepositoryCheckoutBinding:
        for binding in self.bindings:
            if (
                binding.organization_id == organization_id
                and binding.repository == repository
            ):
                return binding
        raise RepositoryCheckoutCatalogError(
            "Onboarding-intentets repository har ingen godkendt checkout "
            "i repository-kataloget"
        )


def catalog_configured(environment: Mapping[str, str] | None = None) -> bool:
    """Return whether catalog mode is configured, rejecting partial configuration."""
    values = os.environ if environment is None else environment
    root_value = values.get(_CATALOG_ROOT_ENV, "").strip()
    catalog_value = values.get(_CATALOG_FILE_ENV, "").strip()
    if bool(root_value) != bool(catalog_value):
        missing = _CATALOG_ROOT_ENV if not root_value else _CATALOG_FILE_ENV
        raise RepositoryCheckoutCatalogError(
            f"Repository checkout-katalog er delvist konfigureret; {missing} mangler"
        )
    return bool(root_value and catalog_value)


def discover_repositories_for_organization(
    organization_id: str,
    environment: Mapping[str, str] | None = None,
) -> tuple[str, ...] | None:
    """Return governed identities, or None when repository discovery is absent."""
    values = os.environ if environment is None else environment
    if catalog_configured(values):
        return RepositoryCheckoutCatalog.from_environment(values).repositories_for(
            organization_id
        )

    legacy_values = (
        values.get(_LEGACY_ORGANIZATION_ENV, "").strip(),
        values.get(_LEGACY_REPOSITORY_ENV, "").strip(),
        values.get(_LEGACY_ROOT_ENV, "").strip(),
    )
    if not any(legacy_values):
        return None
    binding = RepositoryCheckoutBinding.from_legacy_environment(values)
    if binding.organization_id != organization_id:
        return tuple()
    return (binding.repository,)


def discover_repository_checkout(
    *,
    organization_id: str,
    repository: str,
    environment: Mapping[str, str] | None = None,
) -> RepositoryCheckoutBinding:
    """Resolve one exact intent identity to a server-owned checkout binding."""
    values = os.environ if environment is None else environment
    if catalog_configured(values):
        return RepositoryCheckoutCatalog.from_environment(values).binding_for(
            organization_id=organization_id,
            repository=repository,
        )
    binding = RepositoryCheckoutBinding.from_legacy_environment(values)
    binding.root_for(
        organization_id=organization_id,
        repository=repository,
    )
    return binding


def _required_text(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value:
        raise RepositoryCheckoutCatalogError(
            f"{field_name} skal være en ikke-tom streng"
        )
    _validate_exact_text(value, field_name)
    return value


def _validate_exact_text(value: str, field_name: str) -> None:
    if not value or value != value.strip():
        raise RepositoryCheckoutCatalogError(
            f"{field_name} skal være canonical tekst uden outer whitespace"
        )


def _validate_repository(repository: str, field_name: str) -> None:
    _validate_exact_text(repository, field_name)
    if any(character in repository for character in _AUTHORITY_GLOB_CHARS):
        raise RepositoryCheckoutCatalogError(
            f"{field_name} skal være en eksakt repository identity "
            "uden authority wildcards"
        )


def _validate_absolute_directory(path: Path, field_name: str) -> Path:
    if not path.is_absolute():
        raise RepositoryCheckoutCatalogError(
            f"{field_name} skal være en absolut server-side sti"
        )
    resolved = path.resolve()
    if not resolved.is_dir():
        raise RepositoryCheckoutCatalogError(
            f"{field_name} findes ikke som directory"
        )
    return resolved


def _resolve_catalog_checkout(
    root: Path,
    checkout: str,
    *,
    field_name: str,
) -> Path:
    relative = Path(checkout)
    if relative.is_absolute() or relative == Path(".") or ".." in relative.parts:
        raise RepositoryCheckoutCatalogError(
            f"{field_name} skal være en relativ sti under {_CATALOG_ROOT_ENV}"
        )
    candidate = (root / relative).resolve()
    if not candidate.is_relative_to(root):
        raise RepositoryCheckoutCatalogError(
            f"{field_name} må ikke escape {_CATALOG_ROOT_ENV}"
        )
    if not candidate.is_dir():
        raise RepositoryCheckoutCatalogError(
            f"{field_name} peger ikke på en eksisterende checkout"
        )
    return candidate
