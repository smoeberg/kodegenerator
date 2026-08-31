"""Canonical governed API for tenant-owned bot configuration."""

from fastapi import APIRouter, Depends, HTTPException, Query, status

from api.auth import User, get_current_active_user
from api.dependencies import (
    get_bot_catalog_service,
    get_council_configuration_store,
    get_dor,
)
from api.schemas.bot_governance import (
    AllocationCreateRequest,
    AllocationResponse,
    ConnectionCreateRequest,
    ConnectionResponse,
    DeploymentCreateRequest,
    DeploymentResponse,
    DisableRequest,
    ProfileCreateRequest,
    ProfileResponse,
    RoleCreateRequest,
    RoleResponse,
    StageRequest,
    TemplateCreateRequest,
    TemplateResponse,
)
from domain.principal import Principal
from infrastructure.persistence.bot_catalog_store import (
    BotCatalogConflictError,
    BotCatalogNotFoundError,
)
from infrastructure.persistence.council_configuration_store import (
    CouncilConfigurationConflictError,
    CouncilConfigurationError,
    CouncilConfigurationStore,
)
from phase4.agent_registry.bot_profiles import (
    BotBudgetPolicy,
    BotDataPolicy,
    BotProfile,
    ModelDeployment,
    ProviderConnection,
)
from phase4.council.configuration import (
    AllocationMember,
    AutonomyLevel,
    CouncilRoleDefinition,
    CouncilTemplate,
    IndependenceLevel,
    ProtocolFunction,
    RoleAllocationPool,
    TemplateStage,
)
from runtime.context import ContextError
from runtime.core import CommandAuthorizationError, DORRuntime, NotFoundError
from services.bot_catalog import BotCatalogService, BotCatalogValidationError

router = APIRouter(prefix="/api/v1/bot-governance", tags=["bot-governance"])
MANAGE_CAPABILITY = "bot_catalog.manage"


def _context(runtime: DORRuntime, user: User, organization_id: str):
    return runtime.establish_context(
        principal=Principal(
            id=user.username,
            type="user",
            metadata={"username": user.username},
        ),
        organization_id=organization_id,
        actor_id=user.username,
    )


def _authorize(
    runtime: DORRuntime,
    user: User,
    organization_id: str,
    command_id: str,
    resource_id: str,
) -> None:
    try:
        context = _context(runtime, user, organization_id)
        runtime.authority.require_capability(
            context,
            capability_id=MANAGE_CAPABILITY,
            command_id=command_id,
            command_type="BotCatalogCommand",
            resource_id=resource_id,
            resource_organization_id=organization_id,
            aggregate_type="bot_catalog",
        )
    except CommandAuthorizationError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"error": "authorization_denied", "reason": exc.decision.reason},
        ) from exc
    except (ContextError, NotFoundError) as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"error": "organization_context_denied"},
        ) from exc


def _membership(runtime: DORRuntime, user: User, organization_id: str) -> None:
    try:
        _context(runtime, user, organization_id)
    except (ContextError, NotFoundError) as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"error": "organization_context_denied"},
        ) from exc


def _translate(operation):
    try:
        return operation()
    except BotCatalogNotFoundError as exc:
        raise HTTPException(status_code=404, detail={"error": "not_found"}) from exc
    except (
        BotCatalogConflictError,
        CouncilConfigurationConflictError,
    ) as exc:
        raise HTTPException(
            status_code=409, detail={"error": "version_conflict"}
        ) from exc
    except (
        BotCatalogValidationError,
        CouncilConfigurationError,
        TypeError,
        ValueError,
    ) as exc:
        raise HTTPException(
            status_code=422, detail={"error": "invalid_bot_catalog", "reason": str(exc)}
        ) from exc


def _connection(value: ProviderConnection) -> ConnectionResponse:
    return ConnectionResponse(
        connection_id=value.connection_id,
        organization_id=value.organization_id,
        brand=value.brand,
        adapter_type=value.adapter_type,
        endpoint=value.endpoint,
        region=value.region,
        data_boundary=value.data_boundary,
        concurrency_limit=value.concurrency_limit,
        enabled=value.enabled,
        version=value.version,
        fingerprint=value.fingerprint,
        created_at=value.created_at,
        updated_at=value.updated_at,
    )


def _deployment(value: ModelDeployment) -> DeploymentResponse:
    return DeploymentResponse(
        deployment_id=value.deployment_id,
        organization_id=value.organization_id,
        connection_id=value.connection_id,
        connection_version=value.connection_version,
        model_id=value.model_id,
        model_family=value.model_family,
        max_context_tokens=value.max_context_tokens,
        max_output_tokens=value.max_output_tokens,
        structured_output=value.structured_output,
        tool_capabilities=list(value.tool_capabilities),
        status=value.status,
        revision=value.revision,
        fingerprint=value.fingerprint,
        created_at=value.created_at,
        updated_at=value.updated_at,
    )


def _profile(value: BotProfile) -> ProfileResponse:
    return ProfileResponse(
        bot_profile_id=value.bot_profile_id,
        organization_id=value.organization_id,
        agent_identity=value.agent_identity,
        display_name=value.display_name,
        deployment_id=value.deployment_id,
        deployment_revision=value.deployment_revision,
        prompt_version=value.prompt_version,
        capabilities=list(value.capabilities),
        permitted_tools=list(value.permitted_tools),
        data_policy=value.data_policy.canonical(),
        budget_policy=value.budget_policy.canonical(),
        concurrency_limit=value.concurrency_limit,
        enabled=value.enabled,
        version=value.version,
        fingerprint=value.fingerprint,
        created_at=value.created_at,
        updated_at=value.updated_at,
    )


@router.post("/connections", response_model=ConnectionResponse, status_code=201)
def create_connection(
    request: ConnectionCreateRequest,
    organization_id: str = Query(...),
    user: User = Depends(get_current_active_user),
    runtime: DORRuntime = Depends(get_dor),
    service: BotCatalogService = Depends(get_bot_catalog_service),
):
    _authorize(
        runtime, user, organization_id, request.command_id, request.connection_id
    )
    value = ProviderConnection(
        **request.model_dump(exclude={"command_id"}), organization_id=organization_id
    )
    return _connection(_translate(lambda: service.create_connection(value)))


@router.get("/connections", response_model=list[ConnectionResponse])
def list_connections(
    organization_id: str = Query(...),
    include_disabled: bool = True,
    user: User = Depends(get_current_active_user),
    runtime: DORRuntime = Depends(get_dor),
    service: BotCatalogService = Depends(get_bot_catalog_service),
):
    _membership(runtime, user, organization_id)
    return [
        _connection(value)
        for value in service.store.list_connections(
            organization_id, include_disabled=include_disabled
        )
    ]


@router.post("/connections/{connection_id}/disable", response_model=ConnectionResponse)
def disable_connection(
    connection_id: str,
    request: DisableRequest,
    organization_id: str = Query(...),
    user: User = Depends(get_current_active_user),
    runtime: DORRuntime = Depends(get_dor),
    service: BotCatalogService = Depends(get_bot_catalog_service),
):
    _authorize(runtime, user, organization_id, request.command_id, connection_id)
    return _connection(
        _translate(lambda: service.disable_connection(organization_id, connection_id))
    )


@router.post("/deployments", response_model=DeploymentResponse, status_code=201)
def create_deployment(
    request: DeploymentCreateRequest,
    organization_id: str = Query(...),
    user: User = Depends(get_current_active_user),
    runtime: DORRuntime = Depends(get_dor),
    service: BotCatalogService = Depends(get_bot_catalog_service),
):
    _authorize(
        runtime, user, organization_id, request.command_id, request.deployment_id
    )
    data = request.model_dump(exclude={"command_id"})
    data["tool_capabilities"] = tuple(sorted(set(data["tool_capabilities"])))
    return _deployment(
        _translate(
            lambda: service.create_deployment(
                ModelDeployment(**data, organization_id=organization_id)
            )
        )
    )


@router.get("/deployments", response_model=list[DeploymentResponse])
def list_deployments(
    organization_id: str = Query(...),
    user: User = Depends(get_current_active_user),
    runtime: DORRuntime = Depends(get_dor),
    service: BotCatalogService = Depends(get_bot_catalog_service),
):
    _membership(runtime, user, organization_id)
    return [
        _deployment(value) for value in service.store.list_deployments(organization_id)
    ]


@router.post("/deployments/{deployment_id}/disable", response_model=DeploymentResponse)
def disable_deployment(
    deployment_id: str,
    request: DisableRequest,
    organization_id: str = Query(...),
    user: User = Depends(get_current_active_user),
    runtime: DORRuntime = Depends(get_dor),
    service: BotCatalogService = Depends(get_bot_catalog_service),
):
    _authorize(runtime, user, organization_id, request.command_id, deployment_id)
    return _deployment(
        _translate(lambda: service.disable_deployment(organization_id, deployment_id))
    )


@router.post("/profiles", response_model=ProfileResponse, status_code=201)
def create_profile(
    request: ProfileCreateRequest,
    organization_id: str = Query(...),
    user: User = Depends(get_current_active_user),
    runtime: DORRuntime = Depends(get_dor),
    service: BotCatalogService = Depends(get_bot_catalog_service),
):
    _authorize(
        runtime, user, organization_id, request.command_id, request.bot_profile_id
    )
    data = request.model_dump(exclude={"command_id", "data_policy", "budget_policy"})
    data["capabilities"] = tuple(sorted(set(data["capabilities"])))
    data["permitted_tools"] = tuple(sorted(set(data["permitted_tools"])))
    value = BotProfile(
        **data,
        organization_id=organization_id,
        data_policy=BotDataPolicy(
            **request.data_policy.model_dump()
            | {
                "allowed_regions": tuple(
                    sorted(set(request.data_policy.allowed_regions))
                )
            }
        ),
        budget_policy=BotBudgetPolicy(**request.budget_policy.model_dump()),
    )
    return _profile(_translate(lambda: service.create_profile(value)))


@router.get("/profiles", response_model=list[ProfileResponse])
def list_profiles(
    organization_id: str = Query(...),
    include_disabled: bool = True,
    user: User = Depends(get_current_active_user),
    runtime: DORRuntime = Depends(get_dor),
    service: BotCatalogService = Depends(get_bot_catalog_service),
):
    _membership(runtime, user, organization_id)
    return [
        _profile(value)
        for value in service.store.list_profiles(
            organization_id, include_disabled=include_disabled
        )
    ]


@router.post("/profiles/{bot_profile_id}/disable", response_model=ProfileResponse)
def disable_profile(
    bot_profile_id: str,
    request: DisableRequest,
    organization_id: str = Query(...),
    user: User = Depends(get_current_active_user),
    runtime: DORRuntime = Depends(get_dor),
    service: BotCatalogService = Depends(get_bot_catalog_service),
):
    _authorize(runtime, user, organization_id, request.command_id, bot_profile_id)
    return _profile(
        _translate(lambda: service.disable_profile(organization_id, bot_profile_id))
    )


def _role(value: CouncilRoleDefinition) -> RoleResponse:
    return RoleResponse(
        **value.canonical(), fingerprint=value.fingerprint, created_at=value.created_at
    )


def _template(value: CouncilTemplate) -> TemplateResponse:
    return TemplateResponse(
        template_id=value.template_id,
        organization_id=value.organization_id,
        name=value.name,
        stages=[StageRequest(**stage.canonical()) for stage in value.stages],
        approved_by=value.approved_by,
        enabled=value.enabled,
        version=value.version,
        fingerprint=value.fingerprint,
        created_at=value.created_at,
    )


def _allocation(value: RoleAllocationPool) -> AllocationResponse:
    return AllocationResponse(
        allocation_id=value.allocation_id,
        organization_id=value.organization_id,
        role_id=value.role_id,
        role_version=value.role_version,
        members=[member.canonical() for member in value.members],
        independence_level=value.independence_level.value,
        autonomy_level=value.autonomy_level.value,
        hard_constraints=dict(value.hard_constraints),
        approved_by=value.approved_by,
        enabled=value.enabled,
        version=value.version,
        fingerprint=value.fingerprint,
        created_at=value.created_at,
    )


@router.post("/roles", response_model=RoleResponse, status_code=201)
def create_role(
    request: RoleCreateRequest,
    organization_id: str = Query(...),
    user: User = Depends(get_current_active_user),
    runtime: DORRuntime = Depends(get_dor),
    store: CouncilConfigurationStore = Depends(get_council_configuration_store),
):
    _authorize(runtime, user, organization_id, request.command_id, request.role_id)
    data = request.model_dump(exclude={"command_id", "protocol_function"})
    data["required_capabilities"] = tuple(sorted(set(data["required_capabilities"])))
    value = CouncilRoleDefinition(
        **data,
        organization_id=organization_id,
        protocol_function=ProtocolFunction(request.protocol_function),
    )
    return _role(_translate(lambda: store.add_role(value)))


@router.get("/roles", response_model=list[RoleResponse])
def list_roles(
    organization_id: str = Query(...),
    user: User = Depends(get_current_active_user),
    runtime: DORRuntime = Depends(get_dor),
    store: CouncilConfigurationStore = Depends(get_council_configuration_store),
):
    _membership(runtime, user, organization_id)
    return [_role(value) for value in store.list_roles(organization_id)]


@router.post("/templates", response_model=TemplateResponse, status_code=201)
def create_template(
    request: TemplateCreateRequest,
    organization_id: str = Query(...),
    user: User = Depends(get_current_active_user),
    runtime: DORRuntime = Depends(get_dor),
    store: CouncilConfigurationStore = Depends(get_council_configuration_store),
):
    _authorize(runtime, user, organization_id, request.command_id, request.template_id)
    stages = tuple(
        TemplateStage(
            stage_id=stage.stage_id,
            protocol_function=ProtocolFunction(stage.protocol_function),
            role_versions=tuple(sorted(set(stage.role_versions))),
            minimum_assignments=stage.minimum_assignments,
            maximum_assignments=stage.maximum_assignments,
            parallel=stage.parallel,
            blocking=stage.blocking,
        )
        for stage in request.stages
    )
    value = CouncilTemplate(
        template_id=request.template_id,
        organization_id=organization_id,
        name=request.name,
        stages=stages,
        approved_by=request.approved_by,
        enabled=request.enabled,
    )
    return _template(_translate(lambda: store.add_template(value)))


@router.get("/templates", response_model=list[TemplateResponse])
def list_templates(
    organization_id: str = Query(...),
    user: User = Depends(get_current_active_user),
    runtime: DORRuntime = Depends(get_dor),
    store: CouncilConfigurationStore = Depends(get_council_configuration_store),
):
    _membership(runtime, user, organization_id)
    return [_template(value) for value in store.list_templates(organization_id)]


@router.post("/allocations", response_model=AllocationResponse, status_code=201)
def create_allocation(
    request: AllocationCreateRequest,
    organization_id: str = Query(...),
    user: User = Depends(get_current_active_user),
    runtime: DORRuntime = Depends(get_dor),
    store: CouncilConfigurationStore = Depends(get_council_configuration_store),
):
    _authorize(
        runtime, user, organization_id, request.command_id, request.allocation_id
    )
    value = RoleAllocationPool(
        allocation_id=request.allocation_id,
        organization_id=organization_id,
        role_id=request.role_id,
        role_version=request.role_version,
        members=tuple(
            AllocationMember(**member.model_dump()) for member in request.members
        ),
        independence_level=IndependenceLevel(request.independence_level),
        autonomy_level=AutonomyLevel(request.autonomy_level),
        hard_constraints=tuple(sorted(request.hard_constraints.items())),
        approved_by=request.approved_by,
        enabled=request.enabled,
    )
    return _allocation(_translate(lambda: store.add_allocation(value)))


@router.get("/allocations/{allocation_id}", response_model=AllocationResponse)
def get_allocation(
    allocation_id: str,
    organization_id: str = Query(...),
    user: User = Depends(get_current_active_user),
    runtime: DORRuntime = Depends(get_dor),
    store: CouncilConfigurationStore = Depends(get_council_configuration_store),
):
    _membership(runtime, user, organization_id)
    value = store.get_allocation(organization_id, allocation_id)
    if value is None:
        raise HTTPException(status_code=404, detail={"error": "not_found"})
    return _allocation(value)
