import pytest

from api.schemas.bot_governance import (
    ConnectionCreateRequest,
    DeploymentCreateRequest,
    ProfileCreateRequest,
    RoleCreateRequest,
    TemplateCreateRequest,
)
from dashboard.governance_catalog import CREATE_EXAMPLES, resource_path


def test_unknown_resource_is_rejected():
    with pytest.raises(ValueError, match="Unsupported"):
        resource_path("imaginary")


def test_dashboard_examples_match_versioned_api_contracts():
    schemas = {
        "connections": ConnectionCreateRequest,
        "deployments": DeploymentCreateRequest,
        "profiles": ProfileCreateRequest,
        "roles": RoleCreateRequest,
        "templates": TemplateCreateRequest,
    }
    for resource, schema in schemas.items():
        schema.model_validate(CREATE_EXAMPLES[resource])
