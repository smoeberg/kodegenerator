"""
Tests for Prompt Engine Service

Tests cover:
- Template selection based on task phase
- Determinism (same input -> same prompt)
- Inclusion of acceptance criteria
- Correct substitution of placeholders
- Fingerprint consistency
- Prompt validation
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

import pytest

from services.prompt_engine import (
    PromptEngine,
    PromptEngineError,
    PromptGenerationResult,
    PromptPhase,
    WBSContext,
)
from domain.architecture_contract_v1 import (
    ArchitectureContractV1,
    LayerV1,
    DependencyRuleV1,
    QualityGateV1,
)
from domain.task import Task, TaskStatus, TaskPriority
from services.wbs_orchestrator import TaskPhase


class TestPromptEngineInitialization:
    """Tests for PromptEngine initialization."""
    
    def test_initialization_with_valid_templates_dir(self, tmp_path):
        """Test initialization with valid templates directory."""
        templates_dir = tmp_path / "templates" / "prompts"
        templates_dir.mkdir(parents=True)
        
        (templates_dir / "DOMAIN_MODELS.md").write_text("# Test Template\n{task_id}")
        
        engine = PromptEngine(
            repository_root=tmp_path,
            templates_dir=templates_dir,
        )
        
        assert engine.repository_root == tmp_path
        assert engine.templates_dir == templates_dir
    
    def test_initialization_with_nonexistent_templates_dir(self, tmp_path):
        """Test initialization with non-existent templates directory."""
        nonexistent_dir = tmp_path / "nonexistent"
        
        with pytest.raises(PromptEngineError, match="Templates directory not found"):
            PromptEngine(
                repository_root=tmp_path,
                templates_dir=nonexistent_dir,
            )
    
    def test_list_available_templates(self, tmp_path):
        """Test listing available templates."""
        templates_dir = tmp_path / "templates" / "prompts"
        templates_dir.mkdir(parents=True)
        
        for phase in ["DOMAIN_MODELS", "SERVICE_LAYER", "API"]:
            (templates_dir / f"{phase}.md").write_text(f"# {phase} Template")
        
        engine = PromptEngine(
            repository_root=tmp_path,
            templates_dir=templates_dir,
        )
        
        available = engine.list_available_templates()
        
        assert "DOMAIN_MODELS" in available
        assert "SERVICE_LAYER" in available
        assert "API" in available


class TestPromptGeneration:
    """Tests for prompt generation."""
    
    @pytest.fixture
    def engine(self, tmp_path):
        """Create a prompt engine with test templates."""
        templates_dir = tmp_path / "templates" / "prompts"
        templates_dir.mkdir(parents=True)
        
        template_content = """# Test Template
Phase: {task_id}
Contract: {contract_id}
Project: {project_name}
Version: {contract_version}
Task: {task_name}
Description: {task_description}
Acceptance Criteria: {acceptance_criteria}
"""
        (templates_dir / "DOMAIN_MODELS.md").write_text(template_content)
        
        return PromptEngine(
            repository_root=tmp_path,
            templates_dir=templates_dir,
        )
    
    @pytest.fixture
    def sample_contract(self):
        """Create a sample architecture contract."""
        domain_layer = LayerV1(
            id="domain",
            path="src/domain",
            description="Domain layer",
        )
        
        rule = DependencyRuleV1(
            id="DEP-001",
            source="domain",
            may_depend_on=("domain",),
            severity="block",
        )
        
        gate = QualityGateV1(
            id="gate-1",
            type="architecture_tests",
            required=True,
        )
        
        contract = ArchitectureContractV1(
            schema_version="1.0",
            contract_id="test-contract-1",
            version="1.0.0",
            status="draft",
            project_name="Test Project",
            style="hexagonal",
            language="python",
            layers=(domain_layer,),
            dependency_rules=(rule,),
            quality_gates=(gate,),
        )
        
        return contract
    
    @pytest.fixture
    def sample_task(self):
        """Create a sample task."""
        task = Task(
            id="task-123",
            name="Create User Domain Model",
            description="Create domain model for user management",
            status=TaskStatus.PENDING,
            priority=TaskPriority.HIGH,
            metadata={
                "phase": "DOMAIN_MODELS",
                "layer": "domain",
                "layer_id": "domain",
                "acceptance_criteria": [
                    "User entity with validation",
                    "User repository interface",
                    "Unit tests for User entity",
                ],
            },
        )
        
        return task
    
    def test_build_task_prompt_basic(self, engine, sample_contract, sample_task):
        """Test basic prompt generation."""
        repo_context = {
            "framework": "FastAPI",
            "api_base_path": "/api/v1",
        }
        
        wbs_context = WBSContext(
            task=sample_task,
            contract=sample_contract,
            repo_context=repo_context,
            ast_policy=None,
        )
        
        result = engine.build_task_prompt(wbs_context)
        
        assert isinstance(result, PromptGenerationResult)
        assert result.task_id == sample_task.id
        assert result.contract_id == sample_contract.contract_id
        assert result.phase == PromptPhase.DOMAIN_MODELS
        assert len(result.fingerprint) == 64  # SHA-256 hash length
        assert result.prompt is not None
        assert len(result.prompt) > 0
    
    def test_build_task_prompt_contains_task_info(self, engine, sample_contract, sample_task):
        """Test that prompt contains task information."""
        repo_context = {}
        
        wbs_context = WBSContext(
            task=sample_task,
            contract=sample_contract,
            repo_context=repo_context,
            ast_policy=None,
        )
        
        result = engine.build_task_prompt(wbs_context)
        
        assert sample_task.id in result.prompt
        assert sample_task.name in result.prompt
        assert sample_task.description in result.prompt
    
    def test_build_task_prompt_contains_contract_info(self, engine, sample_contract, sample_task):
        """Test that prompt contains contract information."""
        repo_context = {}
        
        wbs_context = WBSContext(
            task=sample_task,
            contract=sample_contract,
            repo_context=repo_context,
            ast_policy=None,
        )
        
        result = engine.build_task_prompt(wbs_context)
        
        assert sample_contract.contract_id in result.prompt
        assert sample_contract.project_name in result.prompt
        assert sample_contract.version in result.prompt
    
    def test_build_task_prompt_contains_acceptance_criteria(self, engine, sample_contract, sample_task):
        """Test that prompt contains acceptance criteria."""
        repo_context = {}
        
        wbs_context = WBSContext(
            task=sample_task,
            contract=sample_contract,
            repo_context=repo_context,
            ast_policy=None,
        )
        
        result = engine.build_task_prompt(wbs_context)
        
        for criterion in sample_task.metadata.get("acceptance_criteria", []):
            assert criterion in result.prompt


class TestPromptDeterminism:
    """Tests for prompt determinism."""
    
    @pytest.fixture
    def engine(self, tmp_path):
        """Create a prompt engine with test templates."""
        templates_dir = tmp_path / "templates" / "prompts"
        templates_dir.mkdir(parents=True)
        
        template_content = """# Test Template
Task ID: {task_id}
Contract ID: {contract_id}
Phase: {task_name}
"""
        (templates_dir / "DOMAIN_MODELS.md").write_text(template_content)
        
        return PromptEngine(
            repository_root=tmp_path,
            templates_dir=templates_dir,
        )
    
    @pytest.fixture
    def sample_contract(self):
        """Create a deterministic sample contract."""
        domain_layer = LayerV1(
            id="domain",
            path="src/domain",
            description="Domain layer",
        )
        
        rule = DependencyRuleV1(
            id="DEP-001",
            source="domain",
            may_depend_on=("domain",),
            severity="block",
        )
        
        gate = QualityGateV1(
            id="gate-1",
            type="architecture_tests",
            required=True,
        )
        
        contract = ArchitectureContractV1(
            schema_version="1.0",
            contract_id="deterministic-contract",
            version="1.0.0",
            status="draft",
            project_name="Deterministic Project",
            style="hexagonal",
            language="python",
            layers=(domain_layer,),
            dependency_rules=(rule,),
            quality_gates=(gate,),
        )
        
        return contract
    
    @pytest.fixture
    def sample_task(self):
        """Create a deterministic sample task."""
        task = Task(
            id="deterministic-task",
            name="Deterministic Task",
            description="A task for testing determinism",
            status=TaskStatus.PENDING,
            priority=TaskPriority.MEDIUM,
            metadata={
                "phase": "DOMAIN_MODELS",
                "layer": "domain",
                "layer_id": "domain",
                "acceptance_criteria": ["Criteria 1", "Criteria 2"],
            },
        )
        
        return task
    
    def test_same_input_produces_same_prompt(self, engine, sample_contract, sample_task):
        """Test that same input always produces same prompt."""
        repo_context = {"framework": "FastAPI"}
        
        wbs_context = WBSContext(
            task=sample_task,
            contract=sample_contract,
            repo_context=repo_context,
            ast_policy=None,
        )
        
        result1 = engine.build_task_prompt(wbs_context)
        result2 = engine.build_task_prompt(wbs_context)
        
        assert result1.prompt == result2.prompt
        assert result1.fingerprint == result2.fingerprint
    
    def test_deterministic_method_produces_same_result(self, engine, sample_contract, sample_task):
        """Test that build_task_prompt_deterministic produces consistent results."""
        repo_context = {"framework": "FastAPI"}
        
        result1 = engine.build_task_prompt_deterministic(
            task=sample_task,
            contract=sample_contract,
            repo_context=repo_context,
            ast_policy=None,
        )
        
        result2 = engine.build_task_prompt_deterministic(
            task=sample_task,
            contract=sample_contract,
            repo_context=repo_context,
            ast_policy=None,
        )
        
        assert result1.prompt == result2.prompt
        assert result1.fingerprint == result2.fingerprint
    
    def test_different_inputs_produce_different_prompts(self, engine, sample_contract, sample_task):
        """Test that different inputs produce different prompts."""
        repo_context = {"framework": "FastAPI"}
        
        task1 = sample_task
        task2 = Task(
            id="different-task",
            name="Different Task",
            description="A different task",
            status=TaskStatus.PENDING,
            priority=TaskPriority.MEDIUM,
            metadata={
                "phase": "DOMAIN_MODELS",
                "layer": "domain",
                "layer_id": "domain",
                "acceptance_criteria": ["Different criteria"],
            },
        )
        
        wbs_context1 = WBSContext(
            task=task1,
            contract=sample_contract,
            repo_context=repo_context,
            ast_policy=None,
        )
        
        wbs_context2 = WBSContext(
            task=task2,
            contract=sample_contract,
            repo_context=repo_context,
            ast_policy=None,
        )
        
        result1 = engine.build_task_prompt(wbs_context1)
        result2 = engine.build_task_prompt(wbs_context2)
        
        assert result1.prompt != result2.prompt
        assert result1.fingerprint != result2.fingerprint


class TestPromptPhaseSelection:
    """Tests for phase selection."""
    
    @pytest.fixture
    def engine(self, tmp_path):
        """Create a prompt engine with test templates."""
        templates_dir = tmp_path / "templates" / "prompts"
        templates_dir.mkdir(parents=True)
        
        for phase in PromptPhase:
            (templates_dir / f"{phase.value}.md").write_text(f"# {phase.value} Template\n{phase.value}")
        
        return PromptEngine(
            repository_root=tmp_path,
            templates_dir=templates_dir,
        )
    
    @pytest.fixture
    def sample_contract(self):
        """Create a sample contract."""
        domain_layer = LayerV1(id="domain", path="src/domain")
        rule = DependencyRuleV1(id="DEP-001", source="domain", may_depend_on=("domain",), severity="block")
        gate = QualityGateV1(id="gate-1", type="architecture_tests", required=True)
        
        contract = ArchitectureContractV1(
            schema_version="1.0",
            contract_id="test-contract",
            version="1.0.0",
            status="draft",
            project_name="Test",
            style="hexagonal",
            language="python",
            layers=(domain_layer,),
            dependency_rules=(rule,),
            quality_gates=(gate,),
        )
        
        return contract
    
    def test_domain_models_phase_selection(self, engine, sample_contract):
        """Test DOMAIN_MODELS phase selection."""
        task = Task(
            id="task-1",
            name="Domain Task",
            metadata={"phase": "DOMAIN_MODELS"},
        )
        
        phase = engine.get_template_phase(task)
        assert phase == PromptPhase.DOMAIN_MODELS
    
    def test_service_layer_phase_selection(self, engine, sample_contract):
        """Test SERVICE_LAYER phase selection."""
        task = Task(
            id="task-1",
            name="Service Task",
            metadata={"phase": "SERVICE_LAYER"},
        )
        
        phase = engine.get_template_phase(task)
        assert phase == PromptPhase.SERVICE_LAYER
    
    def test_api_phase_selection(self, engine, sample_contract):
        """Test API phase selection."""
        task = Task(
            id="task-1",
            name="API Task",
            metadata={"phase": "API"},
        )
        
        phase = engine.get_template_phase(task)
        assert phase == PromptPhase.API
    
    def test_tests_phase_selection(self, engine, sample_contract):
        """Test TESTS phase selection."""
        task = Task(
            id="task-1",
            name="Test Task",
            metadata={"phase": "TESTS"},
        )
        
        phase = engine.get_template_phase(task)
        assert phase == PromptPhase.TESTS
    
    def test_docs_phase_selection(self, engine, sample_contract):
        """Test DOCS phase selection."""
        task = Task(
            id="task-1",
            name="Docs Task",
            metadata={"phase": "DOCS"},
        )
        
        phase = engine.get_template_phase(task)
        assert phase == PromptPhase.DOCS
    
    def test_security_phase_selection(self, engine, sample_contract):
        """Test SECURITY phase selection."""
        task = Task(
            id="task-1",
            name="Security Task",
            metadata={"phase": "SECURITY"},
        )
        
        phase = engine.get_template_phase(task)
        assert phase == PromptPhase.SECURITY
    
    def test_default_phase_selection(self, engine, sample_contract):
        """Test default phase selection when phase not specified."""
        task = Task(
            id="task-1",
            name="Default Task",
            metadata={},  # No phase specified
        )
        
        phase = engine.get_template_phase(task)
        assert phase == PromptPhase.DOMAIN_MODELS  # Default


class TestPromptValidation:
    """Tests for prompt validation."""
    
    @pytest.fixture
    def engine(self, tmp_path):
        """Create a prompt engine with test templates."""
        templates_dir = tmp_path / "templates" / "prompts"
        templates_dir.mkdir(parents=True)
        
        template_content = """# Complete Template

## ROLE & CAPABILITIES
{task_id}

## ARCHITECTURE CONTEXT
Project: {project_name}
Contract: {contract_id}
Version: {contract_version}

## AST POLICY & SECURITY RULES
{task_name}

## ACCEPTANCE CRITERIA
{acceptance_criteria}

## OUTPUT REQUIREMENTS
{output_files_str}

## TASK INSTRUCTION
{task_description}
"""
        (templates_dir / "DOMAIN_MODELS.md").write_text(template_content)
        
        return PromptEngine(
            repository_root=tmp_path,
            templates_dir=templates_dir,
        )
    
    @pytest.fixture
    def sample_contract(self):
        """Create a sample contract."""
        domain_layer = LayerV1(id="domain", path="src/domain")
        rule = DependencyRuleV1(id="DEP-001", source="domain", may_depend_on=("domain",), severity="block")
        gate = QualityGateV1(id="gate-1", type="architecture_tests", required=True)
        
        contract = ArchitectureContractV1(
            schema_version="1.0",
            contract_id="test-contract",
            version="1.0.0",
            status="draft",
            project_name="Test",
            style="hexagonal",
            language="python",
            layers=(domain_layer,),
            dependency_rules=(rule,),
            quality_gates=(gate,),
        )
        
        return contract
    
    @pytest.fixture
    def sample_task(self):
        """Create a sample task."""
        task = Task(
            id="task-1",
            name="Test Task",
            description="Test description",
            metadata={
                "phase": "DOMAIN_MODELS",
                "acceptance_criteria": ["Criteria 1"],
            },
        )
        
        return task
    
    def test_validate_valid_prompt(self, engine, sample_contract, sample_task):
        """Test validation of a valid prompt."""
        repo_context = {}
        
        wbs_context = WBSContext(
            task=sample_task,
            contract=sample_contract,
            repo_context=repo_context,
            ast_policy=None,
        )
        
        result = engine.build_task_prompt(wbs_context)
        is_valid, errors = engine.validate_prompt(result)
        
        assert is_valid is True
        assert len(errors) == 0
    
    def test_validate_prompt_with_missing_sections(self, engine):
        """Test validation detects missing sections."""
        incomplete_prompt = "# Incomplete\nJust some text"
        
        result = PromptGenerationResult(
            prompt=incomplete_prompt,
            prompt_id="test-id",
            phase=PromptPhase.DOMAIN_MODELS,
            task_id="task-1",
            contract_id="contract-1",
            fingerprint=engine._compute_fingerprint(incomplete_prompt),
            generated_at=datetime.now(timezone.utc),
        )
        
        is_valid, errors = engine.validate_prompt(result)
        
        assert is_valid is False
        assert len(errors) > 0
        assert any("Missing required section" in error for error in errors)
    
    def test_validate_prompt_with_unreplaced_placeholders(self, engine):
        """Test validation detects unreplaced placeholders."""
        # Create a prompt with all required sections but with unreplaced placeholders
        prompt_with_placeholders = """# Complete Template

## ROLE & CAPABILITIES
{task_id}

## ARCHITECTURE CONTEXT
Project: {project_name}
Contract: {contract_id}

## AST POLICY & SECURITY RULES
{task_name}

## ACCEPTANCE CRITERIA
{acceptance_criteria}

## OUTPUT REQUIREMENTS
{output_files_str}

## TASK INSTRUCTION
{unreplaced_placeholder}
"""
        
        result = PromptGenerationResult(
            prompt=prompt_with_placeholders,
            prompt_id="test-id",
            phase=PromptPhase.DOMAIN_MODELS,
            task_id="task-1",
            contract_id="contract-1",
            fingerprint=engine._compute_fingerprint(prompt_with_placeholders),
            generated_at=datetime.now(timezone.utc),
        )
        
        is_valid, errors = engine.validate_prompt(result)
        
        assert is_valid is False
        assert any("Unreplaced placeholders" in error for error in errors)
    
    def test_validate_prompt_fingerprint_mismatch(self, engine):
        """Test validation detects fingerprint mismatch."""
        prompt = "# Test\nContent"
        wrong_fingerprint = "0" * 64  # Wrong fingerprint
        
        result = PromptGenerationResult(
            prompt=prompt,
            prompt_id="test-id",
            phase=PromptPhase.DOMAIN_MODELS,
            task_id="task-1",
            contract_id="contract-1",
            fingerprint=wrong_fingerprint,
            generated_at=datetime.now(timezone.utc),
        )
        
        is_valid, errors = engine.validate_prompt(result)
        
        assert is_valid is False
        assert any("Fingerprint mismatch" in error for error in errors)


class TestPromptToDict:
    """Tests for PromptGenerationResult.to_dict()."""
    
    def test_to_dict_conversion(self):
        """Test conversion to dictionary."""
        result = PromptGenerationResult(
            prompt="# Test Prompt",
            prompt_id="test-id",
            phase=PromptPhase.DOMAIN_MODELS,
            task_id="task-1",
            contract_id="contract-1",
            fingerprint="abc123def456",
            generated_at=datetime(2024, 1, 1, 0, 0, 0, tzinfo=timezone.utc),
        )
        
        result_dict = result.to_dict()
        
        assert result_dict["prompt"] == "# Test Prompt"
        assert result_dict["prompt_id"] == "test-id"
        assert result_dict["phase"] == "DOMAIN_MODELS"
        assert result_dict["task_id"] == "task-1"
        assert result_dict["contract_id"] == "contract-1"
        assert result_dict["fingerprint"] == "abc123def456"
        assert "2024-01-01" in result_dict["generated_at"]


class TestWBSContext:
    """Tests for WBSContext."""
    
    @pytest.fixture
    def sample_contract(self):
        """Create a sample contract."""
        domain_layer = LayerV1(id="domain", path="src/domain")
        rule = DependencyRuleV1(id="DEP-001", source="domain", may_depend_on=("domain",), severity="block")
        gate = QualityGateV1(id="gate-1", type="architecture_tests", required=True)
        
        contract = ArchitectureContractV1(
            schema_version="1.0",
            contract_id="test-contract",
            version="1.0.0",
            status="draft",
            project_name="Test",
            style="hexagonal",
            language="python",
            layers=(domain_layer,),
            dependency_rules=(rule,),
            quality_gates=(gate,),
        )
        
        return contract
    
    @pytest.fixture
    def sample_task(self):
        """Create a sample task."""
        task = Task(
            id="task-1",
            name="Test Task",
            metadata={
                "phase": "SERVICE_LAYER",
                "layer": "application",
            },
        )
        
        return task
    
    def test_wbs_context_task_phase(self, sample_contract, sample_task):
        """Test WBSContext task_phase property."""
        context = WBSContext(
            task=sample_task,
            contract=sample_contract,
            repo_context={},
            ast_policy=None,
        )
        
        assert context.task_phase == TaskPhase.SERVICE_LAYER
    
    def test_wbs_context_layer_name(self, sample_contract, sample_task):
        """Test WBSContext layer_name property."""
        context = WBSContext(
            task=sample_task,
            contract=sample_contract,
            repo_context={},
            ast_policy=None,
        )
        
        assert context.layer_name == "application"
    
    def test_wbs_context_default_phase(self, sample_contract):
        """Test WBSContext default phase."""
        task = Task(
            id="task-1",
            name="Test Task",
            metadata={},  # No phase specified
        )
        
        context = WBSContext(
            task=task,
            contract=sample_contract,
            repo_context={},
            ast_policy=None,
        )
        
        # Default should be DOMAIN_MODELS
        assert context.task_phase == TaskPhase.DOMAIN_MODELS
