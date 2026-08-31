"""Application service for selecting and atomically freezing a Council run."""

from __future__ import annotations

from infrastructure.persistence.bot_catalog_store import BotCatalogStore
from infrastructure.persistence.council_configuration_store import (
    CouncilConfigurationStore,
)
from infrastructure.persistence.selection_store import CouncilSelectionStore
from phase4.verification.allocation_selector import (
    CouncilRunSelection,
    CouncilSelectionError,
    DeterministicCouncilSelector,
    SelectionCandidate,
    SelectionRequestContext,
)


class CouncilSelectionService:
    def __init__(
        self,
        catalog: BotCatalogStore,
        configuration: CouncilConfigurationStore,
        selections: CouncilSelectionStore,
        selector: DeterministicCouncilSelector | None = None,
    ) -> None:
        self._catalog = catalog
        self._configuration = configuration
        self._selections = selections
        self._selector = selector or DeterministicCouncilSelector()

    def select_and_freeze(
        self,
        *,
        organization_id: str,
        run_id: str,
        template_id: str,
        template_version: int,
        allocation_refs: tuple[tuple[str, int], ...],
        context: SelectionRequestContext,
    ) -> CouncilRunSelection:
        replay = self._selections.get(organization_id, run_id)
        if replay is not None:
            if (
                replay.template_id != template_id
                or replay.template_version != template_version
                or replay.context_fingerprint != context.fingerprint
            ):
                raise CouncilSelectionError(
                    "run ID is already frozen for different input"
                )
            return replay
        template = self._configuration.get_template(
            organization_id, template_id, template_version
        )
        if template is None:
            raise CouncilSelectionError("Council template version does not exist")
        allocations = {}
        candidates = {}
        for allocation_id, version in allocation_refs:
            pool = self._configuration.get_allocation(
                organization_id, allocation_id, version
            )
            if pool is None:
                raise CouncilSelectionError("Council allocation version does not exist")
            role_key = (pool.role_id, pool.role_version)
            if role_key in allocations:
                raise CouncilSelectionError("multiple allocations target the same role")
            allocations[role_key] = pool
            for member in pool.members:
                key = (member.bot_profile_id, member.bot_profile_version)
                if key not in candidates:
                    candidates[key] = self._candidate(organization_id, *key)
        selected = self._selector.select(
            run_id=run_id,
            organization_id=organization_id,
            template=template,
            allocations=allocations,
            candidates=candidates,
            context=context,
        )
        return self._selections.freeze(selected)

    def get(self, organization_id: str, run_id: str) -> CouncilRunSelection | None:
        return self._selections.get(organization_id, run_id)

    def get_template(self, organization_id: str, template_id: str, version: int):
        return self._configuration.get_template(organization_id, template_id, version)

    def _candidate(
        self, organization_id: str, profile_id: str, profile_version: int
    ) -> SelectionCandidate:
        profile = self._catalog.get_profile(
            organization_id, profile_id, profile_version
        )
        if profile is None:
            raise CouncilSelectionError("allocated bot profile snapshot is missing")
        deployment = self._catalog.get_deployment(
            organization_id, profile.deployment_id, profile.deployment_revision
        )
        if deployment is None:
            raise CouncilSelectionError("allocated deployment snapshot is missing")
        connection = self._catalog.get_connection(
            organization_id,
            deployment.connection_id,
            deployment.connection_version,
        )
        if connection is None:
            raise CouncilSelectionError("allocated connection snapshot is missing")
        return SelectionCandidate(
            bot_profile_id=profile.bot_profile_id,
            bot_profile_version=profile.version,
            profile_fingerprint=profile.fingerprint,
            agent_identity=profile.agent_identity,
            deployment_id=deployment.deployment_id,
            deployment_revision=deployment.revision,
            deployment_fingerprint=deployment.fingerprint,
            connection_id=connection.connection_id,
            connection_version=connection.version,
            connection_fingerprint=connection.fingerprint,
            provider=connection.adapter_type,
            brand=connection.brand,
            model_family=deployment.model_family,
            data_boundary=connection.data_boundary,
            region=connection.region,
            capabilities=profile.capabilities,
            enabled=profile.enabled and connection.enabled,
            deployment_status=deployment.status,
        )
