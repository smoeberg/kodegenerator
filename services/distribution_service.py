"""P3-19 distribution service.

The service deliberately contains no model call, prompt rewriting, or agent
selection heuristics. Routing is a deterministic projection of the compiled
AgentContractPackage.
"""
from __future__ import annotations

from domain.agent_contract import AgentContractPackage
from domain.distribution import DispatchRecord, DispatchRequest, DistributionError, route


class DistributionService:
    """Safely route a task to one compiled specialist contract."""

    def dispatch(
        self,
        package: AgentContractPackage,
        request: DispatchRequest,
    ) -> DispatchRecord:
        if not isinstance(package, AgentContractPackage):
            raise DistributionError("dispatch requires an AgentContractPackage")
        if not isinstance(request, DispatchRequest):
            raise DistributionError("dispatch requires a DispatchRequest")
        return route(package, request)
