# services/pipeline_adapter.py

from typing import Dict, Any, Optional
import yaml
import uuid
from datetime import datetime
import logging

from domain.workflow import Workflow
from domain.pipeline_states import PipelineState
from domain.pipeline_transitions import get_pipeline_transitions
from domain.pipeline_gates import get_pipeline_gates
from infrastructure.persistence.repositories import WorkflowRepository

logger = logging.getLogger(__name__)

class PipelineAdapter:
    """
    Adapter that takes a YAML requirements specification and creates
    a fully configured Workflow for the software factory pipeline.
    """
    
    def __init__(self, workflow_repository: WorkflowRepository):
        self._workflow_repo = workflow_repository
    
    async def create_pipeline_from_yaml(
        self,
        yaml_content: str,
        organization_id: str,
        created_by: str,
    ) -> Workflow:
        """
        Parse YAML requirements and create a configured Workflow.
        """
        try:
            # 1. Parse YAML
            spec = yaml.safe_load(yaml_content)
            if not spec:
                raise ValueError("Empty or invalid YAML content")
            
            # 2. Validate requirements
            self._validate_spec(spec)
            
            # 3. Create workflow with all pipeline states
            workflow = Workflow(
                id=str(uuid.uuid4()),
                name=f"Pipeline: {spec.get('project_name', 'Unnamed')}",
                current_state=PipelineState.REQUIREMENTS_DRAFT,
                states=list(PipelineState),
                transitions=get_pipeline_transitions(),
                gates=get_pipeline_gates(),
                context={
                    "requirements": spec,
                    "project_name": spec.get("project_name"),
                    "project_description": spec.get("project_description"),
                    "requirements_complete": False,
                    "architecture_generated": False,
                    "contracts_generated": False,
                    "code_generated": False,
                    "tests_generated": False,
                    "tests_passed": False,
                    "deployed": False,
                    "release_complete": False,
                    "error": None,
                    "cancelled": False,
                    "architecture_generation_enabled": True,
                    "contract_generation_enabled": True,
                    "code_generation_enabled": True,
                    "test_generation_enabled": True,
                    "test_execution_enabled": True,
                    "deployment_enabled": True,
                },
                created_at=datetime.utcnow(),
                updated_at=datetime.utcnow(),
                metadata={
                    "organization_id": organization_id,
                    "created_by": created_by,
                    "version": "1.0",
                    "requirements_version": spec.get("version", "1.0"),
                },
            )
            
            # 4. Set organization and creator
            workflow.organization_id = organization_id
            workflow.created_by = created_by
            
            # 5. Save to repository
            await self._workflow_repo.save(workflow)
            
            logger.info(f"Created pipeline workflow {workflow.id} for project {spec.get('project_name')}")
            return workflow
            
        except yaml.YAMLError as e:
            raise ValueError(f"Invalid YAML: {str(e)}")
        except Exception as e:
            logger.error(f"Failed to create pipeline: {str(e)}")
            raise
    
    def parse_spec(self, yaml_content: str) -> Dict[str, Any]:
        """Parse and validate a YAML requirements spec, returning the dict."""
        try:
            spec = yaml.safe_load(yaml_content)
        except yaml.YAMLError as e:
            raise ValueError(f"Invalid YAML: {str(e)}")
        if not spec:
            raise ValueError("Empty or invalid YAML content")
        self._validate_spec(spec)
        return spec

    def _validate_spec(self, spec: Dict[str, Any]) -> None:
        """Validate that requirements spec has required fields"""
        
        required_fields = [
            "project_name",
            "project_description",
            "requirements",
        ]
        for field in required_fields:
            if field not in spec:
                raise ValueError(f"Missing required field: {field}")
        
        # Validate requirements list
        if not isinstance(spec["requirements"], list):
            raise ValueError("'requirements' must be a list")
        
        if len(spec["requirements"]) == 0:
            raise ValueError("At least one requirement is required")
        
        # Validate each requirement
        for req in spec.get("requirements", []):
            if "id" not in req:
                raise ValueError("Each requirement must have an 'id' field")
            if "acceptance_criteria" not in req:
                raise ValueError(f"Requirement {req['id']} missing 'acceptance_criteria'")
            if not req.get("acceptance_criteria"):
                raise ValueError(f"Requirement {req['id']} has empty acceptance criteria")
            if not req.get("description"):
                raise ValueError(f"Requirement {req['id']} missing 'description'")
