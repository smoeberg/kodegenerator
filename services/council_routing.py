"""Resolve frozen Council assignments against exact Bot Catalog versions."""

from infrastructure.persistence.bot_catalog_store import BotCatalogStore
from phase4.council.routing import CatalogRouteSnapshot, ProviderRoutingError
from phase4.verification.allocation_selector import FrozenCouncilAssignment


class BotCatalogRouteResolver:
    def __init__(self, catalog: BotCatalogStore, organization_id: str) -> None:
        self._catalog = catalog
        self._organization_id = organization_id

    def resolve(self, assignment: FrozenCouncilAssignment) -> CatalogRouteSnapshot:
        profile = self._catalog.get_profile(
            self._organization_id,
            assignment.bot_profile_id,
            assignment.bot_profile_version,
        )
        if profile is None or profile.fingerprint != assignment.profile_fingerprint:
            raise ProviderRoutingError("frozen bot profile cannot be resolved")
        deployment = self._catalog.get_deployment(
            self._organization_id,
            assignment.deployment_id,
            assignment.deployment_revision,
        )
        if (
            deployment is None
            or deployment.fingerprint != assignment.deployment_fingerprint
        ):
            raise ProviderRoutingError("frozen deployment cannot be resolved")
        connection = self._catalog.get_connection(
            self._organization_id,
            assignment.connection_id,
            assignment.connection_version,
        )
        if (
            connection is None
            or connection.fingerprint != assignment.connection_fingerprint
        ):
            raise ProviderRoutingError("frozen connection cannot be resolved")
        if (
            profile.deployment_id != deployment.deployment_id
            or profile.deployment_revision != deployment.revision
            or deployment.connection_id != connection.connection_id
            or deployment.connection_version != connection.version
        ):
            raise ProviderRoutingError(
                "catalog lineage does not match frozen assignment"
            )
        return CatalogRouteSnapshot(
            provider_id=connection.connection_id,
            connection_id=connection.connection_id,
            connection_version=connection.version,
            connection_fingerprint=connection.fingerprint,
            deployment_id=deployment.deployment_id,
            deployment_revision=deployment.revision,
            deployment_fingerprint=deployment.fingerprint,
            model_id=deployment.model_id,
            model_family=deployment.model_family,
            prompt_version=profile.prompt_version,
        )
