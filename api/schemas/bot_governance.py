"""Strict HTTP schemas for the versioned Bot Catalog."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class DataPolicyRequest(StrictModel):
    boundary: str = "global"
    allowed_regions: list[str] = Field(default_factory=list)
    source_code_allowed: bool = True


class BudgetPolicyRequest(StrictModel):
    max_cost_minor_units: int | None = Field(default=None, ge=0)
    max_input_tokens: int = Field(default=32_000, ge=1)
    max_output_tokens: int = Field(default=4_096, ge=1)


class ConnectionCreateRequest(StrictModel):
    command_id: str
    connection_id: str
    brand: str
    adapter_type: str
    endpoint: str
    secret_reference: str
    region: str | None = None
    data_boundary: str = "global"
    concurrency_limit: int = Field(default=1, ge=1)
    enabled: bool = True


class DisableRequest(StrictModel):
    command_id: str


class ConnectionResponse(StrictModel):
    connection_id: str
    organization_id: str
    brand: str
    adapter_type: str
    endpoint: str
    region: str | None
    data_boundary: str
    concurrency_limit: int
    enabled: bool
    version: int
    fingerprint: str
    created_at: datetime
    updated_at: datetime


class DeploymentCreateRequest(StrictModel):
    command_id: str
    deployment_id: str
    connection_id: str
    connection_version: int = Field(ge=1)
    model_id: str
    model_family: str
    max_context_tokens: int = Field(ge=1)
    max_output_tokens: int = Field(ge=1)
    structured_output: bool = True
    tool_capabilities: list[str] = Field(default_factory=list)


class DeploymentResponse(StrictModel):
    deployment_id: str
    organization_id: str
    connection_id: str
    connection_version: int
    model_id: str
    model_family: str
    max_context_tokens: int
    max_output_tokens: int
    structured_output: bool
    tool_capabilities: list[str]
    status: str
    revision: int
    fingerprint: str
    created_at: datetime
    updated_at: datetime


class ProfileCreateRequest(StrictModel):
    command_id: str
    bot_profile_id: str
    agent_identity: str
    display_name: str
    deployment_id: str
    deployment_revision: int = Field(ge=1)
    prompt_version: str
    capabilities: list[str]
    permitted_tools: list[str] = Field(default_factory=list)
    data_policy: DataPolicyRequest = Field(default_factory=DataPolicyRequest)
    budget_policy: BudgetPolicyRequest = Field(default_factory=BudgetPolicyRequest)
    concurrency_limit: int = Field(default=1, ge=1)
    enabled: bool = False


class ProfileResponse(StrictModel):
    bot_profile_id: str
    organization_id: str
    agent_identity: str
    display_name: str
    deployment_id: str
    deployment_revision: int
    prompt_version: str
    capabilities: list[str]
    permitted_tools: list[str]
    data_policy: DataPolicyRequest
    budget_policy: BudgetPolicyRequest
    concurrency_limit: int
    enabled: bool
    version: int
    fingerprint: str
    created_at: datetime
    updated_at: datetime
