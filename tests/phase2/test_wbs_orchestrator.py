"""
Tests for WBS Orchestrator Service

Verificerer korrekt DAG-rækkefølge og afhængighedsvalidering.
"""

from __future__ import annotations

import pytest
from datetime import datetime, timezone
from typing import List, Tuple

from domain.task import Task, TaskStatus, TaskPriority, DependencyStatus
from domain.architecture_contract_v1 import (
    ArchitectureContractV1, 
    LayerV1,
    DependencyRuleV1,
    QualityGateV1,
    ConstraintV1,
    DecisionV1,
    TraceLinkV1,
    ExceptionV1,
    ApprovalV1,
)
from services.wbs_orchestrator import (
    WBSOrchestratorService,
    TaskPhase,
    AgentRole,
    AgentCapability,
    WBSTask,
    TASK_TEMPLATES,
)


class TestWBSOrchestratorBasic:
    """Basic functionality tests for WBS Orchestrator."""
    
    def setup_method(self):
        """Setup test fixtures."""
        self.orchestrator = WBSOrchestratorService(organization_id="test-org")
    
    def test_orchestrator_initialization(self):
        """Test that orchestrator initializes correctly."""
        assert self.orchestrator.organization_id == "test-org"
        assert self.orchestrator._task_counter == {}
    
    def test_reset_counters(self):
        """Test that counters can be reset."""
        self.orchestrator._task_counter[TaskPhase.DOMAIN_MODELS] = 5
        self.orchestrator.reset_counters()
        assert self.orchestrator._task_counter == {}
    
    def test_get_next_sequence(self):
        """Test sequence number generation."""
        seq1 = self.orchestrator._get_next_sequence(TaskPhase.DOMAIN_MODELS)
        seq2 = self.orchestrator._get_next_sequence(TaskPhase.DOMAIN_MODELS)
        assert seq1 == 1
        assert seq2 == 2


class TestTaskGeneration:
    """Tests for task generation from templates."""
    
    def setup_method(self):
        """Setup test fixtures."""
        self.orchestrator = WBSOrchestratorService(organization_id="test-org")
    
    def test_create_task_from_template_basic(self):
        """Test basic task creation from template."""
        template = TASK_TEMPLATES[TaskPhase.DOMAIN_MODELS][0]
        layer = LayerV1(id="domain", path="src/domain")
        
        wbs_task = self.orchestrator._create_task_from_template(
            template, layer, workflow_id="test-workflow"
        )
        
        assert isinstance(wbs_task, WBSTask)
        assert wbs_task.phase == TaskPhase.DOMAIN_MODELS
        assert wbs_task.role == template.role
        assert wbs_task.capabilities == template.capabilities
        assert wbs_task.layer_id == "domain"
        assert wbs_task.task.workflow_id == "test-workflow"
        assert wbs_task.task.organization_id == "test-org"
    
    def test_create_task_from_template_name_generation(self):
        """Test that task names are generated correctly."""
        template = TASK_TEMPLATES[TaskPhase.DOMAIN_MODELS][0]
        layer = LayerV1(id="domain", path="src/domain")
        
        wbs_task1 = self.orchestrator._create_task_from_template(
            template, layer, workflow_id="test-workflow"
        )
        wbs_task2 = self.orchestrator._create_task_from_template(
            template, layer, workflow_id="test-workflow"
        )
        
        # Names should include sequence numbers
        assert "01" in wbs_task1.name or "1" in wbs_task1.name
        assert "02" in wbs_task2.name or "2" in wbs_task2.name
    
    def test_create_task_from_template_description(self):
        """Test that task descriptions are formatted correctly."""
        template = TASK_TEMPLATES[TaskPhase.DOMAIN_MODELS][0]
        layer = LayerV1(id="domain", path="src/domain")
        
        wbs_task = self.orchestrator._create_task_from_template(
            template, layer, workflow_id="test-workflow"
        )
        
        assert "src/domain" in wbs_task.task.description
    
    def test_create_task_without_layer(self):
        """Test task creation without a specific layer."""
        template = TASK_TEMPLATES[TaskPhase.VERIFICATION][0]
        
        wbs_task = self.orchestrator._create_task_from_template(
            template, None, workflow_id="test-workflow"
        )
        
        assert wbs_task.layer_id is None
        assert "root" in wbs_task.task.description


class TestDAGGeneration:
    """Tests for DAG generation and validation."""
    
    def setup_method(self):
        """Setup test fixtures."""
        self.orchestrator = WBSOrchestratorService(organization_id="test-org")
        
    def _create_contract(self, layers=None, dependency_rules=None):
        """Helper to create a valid ArchitectureContractV1."""
        if layers is None:
            layers = [
                LayerV1(id="domain", path="src/domain"),
                LayerV1(id="application", path="src/application"),
                LayerV1(id="ports", path="src/ports"),
            ]
        if dependency_rules is None:
            dependency_rules = [
                {"id": "DEP-001", "source": "application", "may_depend_on": ["domain"]},
            ]
        
        return ArchitectureContractV1(
            schema_version="1.0",
            contract_id="test-contract",
            version="1.0.0",
            status="draft",
            project_name="test-project",
            style="hexagonal",
            language="python",
            layers=tuple(layers),
            dependency_rules=tuple(
                DependencyRuleV1(
                    id=rule.get("id", f"DEP-{i}"),
                    source=rule.get("source", "application"),
                    may_depend_on=tuple(rule.get("may_depend_on", ["domain"])),
                    severity=rule.get("severity", "block"),
                )
                for i, rule in enumerate(dependency_rules)
            ),
            quality_gates=(
                QualityGateV1(id="gate-1", type="architecture_tests", required=True),
            ),
            constraints=(),
            decisions=(),
            traceability=(),
            technology_constraints=(),
            exceptions=(),
        )
    
    def test_generate_from_contract_basic(self):
        """Test basic WBS generation from a simple contract."""
        contract = self._create_contract()
        
        tasks, task_map = self.orchestrator.generate_from_contract(contract)
        
        assert len(tasks) > 0
        assert len(task_map) == len(tasks)
        assert all(isinstance(t, WBSTask) for t in tasks)
    
    def test_generate_from_contract_all_phases(self):
        """Test that all phases are represented in generated tasks."""
        contract = self._create_contract()
        
        tasks, _ = self.orchestrator.generate_from_contract(contract)
        
        phases = {task.phase for task in tasks}
        
        # Should have tasks from multiple phases
        assert TaskPhase.DOMAIN_MODELS in phases
        assert TaskPhase.SERVICE_LAYER in phases
        assert TaskPhase.API_ENDPOINTS in phases
        assert TaskPhase.TEST_SUITES in phases
        assert TaskPhase.VERIFICATION in phases
    
    def test_validate_dag_no_cycles(self):
        """Test that a valid DAG passes validation."""
        contract = self._create_contract()
        
        tasks, _ = self.orchestrator.generate_from_contract(contract)
        
        # Should not raise an exception
        assert self.orchestrator.validate_dag(tasks) is True
    
    def test_validate_dag_with_unknown_dependency(self):
        """Test that unknown dependencies are detected."""
        task1 = WBSTask(
            task=Task(
                id="task-1",
                name="Task 1",
                dependencies=["unknown-task"],
            ),
            phase=TaskPhase.DOMAIN_MODELS,
            role=AgentRole.DEVELOPER,
            capabilities=[AgentCapability.CAP_CODE_GENERATION],
        )
        
        with pytest.raises(ValueError, match="unknown task"):
            self.orchestrator.validate_dag([task1])


class TestExecutionOrder:
    """Tests for execution order determination."""
    
    def setup_method(self):
        """Setup test fixtures."""
        self.orchestrator = WBSOrchestratorService(organization_id="test-org")
    
    def test_get_execution_order_basic(self):
        """Test basic execution order determination."""
        # Create tasks with dependencies
        task1 = WBSTask(
            task=Task(
                id="task-1",
                name="Task 1",
                priority=TaskPriority.HIGH,
                dependencies=[],
            ),
            phase=TaskPhase.DOMAIN_MODELS,
            role=AgentRole.DEVELOPER,
            capabilities=[AgentCapability.CAP_CODE_GENERATION],
        )
        
        task2 = WBSTask(
            task=Task(
                id="task-2",
                name="Task 2",
                priority=TaskPriority.HIGH,
                dependencies=["task-1"],
            ),
            phase=TaskPhase.SERVICE_LAYER,
            role=AgentRole.DEVELOPER,
            capabilities=[AgentCapability.CAP_IMPLEMENTATION],
        )
        
        tasks = [task1, task2]
        ordered = self.orchestrator.get_execution_order(tasks)
        
        assert len(ordered) == 2
        assert ordered[0].id == "task-1"
        assert ordered[1].id == "task-2"
    
    def test_get_execution_order_priority(self):
        """Test that priority affects execution order."""
        task1 = WBSTask(
            task=Task(
                id="task-1",
                name="Task 1",
                priority=TaskPriority.LOW,
                dependencies=[],
            ),
            phase=TaskPhase.DOMAIN_MODELS,
            role=AgentRole.DEVELOPER,
            capabilities=[AgentCapability.CAP_CODE_GENERATION],
        )
        
        task2 = WBSTask(
            task=Task(
                id="task-2",
                name="Task 2",
                priority=TaskPriority.HIGH,
                dependencies=[],
            ),
            phase=TaskPhase.DOMAIN_MODELS,
            role=AgentRole.DEVELOPER,
            capabilities=[AgentCapability.CAP_IMPLEMENTATION],
        )
        
        tasks = [task1, task2]
        ordered = self.orchestrator.get_execution_order(tasks)
        
        # Higher priority should come first
        assert ordered[0].id == "task-2"
        assert ordered[1].id == "task-1"
    
    def test_get_execution_order_cycle_detection(self):
        """Test that cycles in dependencies are detected."""
        task1 = WBSTask(
            task=Task(
                id="task-1",
                name="Task 1",
                dependencies=["task-2"],
            ),
            phase=TaskPhase.DOMAIN_MODELS,
            role=AgentRole.DEVELOPER,
            capabilities=[AgentCapability.CAP_CODE_GENERATION],
        )
        
        task2 = WBSTask(
            task=Task(
                id="task-2",
                name="Task 2",
                dependencies=["task-1"],
            ),
            phase=TaskPhase.SERVICE_LAYER,
            role=AgentRole.DEVELOPER,
            capabilities=[AgentCapability.CAP_IMPLEMENTATION],
        )
        
        tasks = [task1, task2]
        
        with pytest.raises(ValueError, match="Cycle detected"):
            self.orchestrator.get_execution_order(tasks)


class TestTaskFiltering:
    """Tests for task filtering capabilities."""
    
    def setup_method(self):
        """Setup test fixtures."""
        self.orchestrator = WBSOrchestratorService(organization_id="test-org")
        
        # Create sample tasks
        self.tasks = [
            WBSTask(
                task=Task(id="task-1", name="Domain Task"),
                phase=TaskPhase.DOMAIN_MODELS,
                role=AgentRole.ARCHITECT,
                capabilities=[AgentCapability.CAP_DOMAIN_MODELING],
            ),
            WBSTask(
                task=Task(id="task-2", name="Service Task"),
                phase=TaskPhase.SERVICE_LAYER,
                role=AgentRole.DEVELOPER,
                capabilities=[AgentCapability.CAP_IMPLEMENTATION],
            ),
            WBSTask(
                task=Task(id="task-3", name="Test Task"),
                phase=TaskPhase.TEST_SUITES,
                role=AgentRole.TEST_ENGINEER,
                capabilities=[AgentCapability.CAP_RUN_TESTS],
            ),
        ]
    
    def test_get_tasks_by_role(self):
        """Test filtering tasks by role."""
        dev_tasks = self.orchestrator.get_tasks_by_role(self.tasks, AgentRole.DEVELOPER)
        
        assert len(dev_tasks) == 1
        assert dev_tasks[0].id == "task-2"
    
    def test_get_tasks_by_phase(self):
        """Test filtering tasks by phase."""
        domain_tasks = self.orchestrator.get_tasks_by_phase(
            self.tasks, TaskPhase.DOMAIN_MODELS
        )
        
        assert len(domain_tasks) == 1
        assert domain_tasks[0].id == "task-1"
    
    def test_get_tasks_by_capability(self):
        """Test filtering tasks by capability."""
        test_tasks = self.orchestrator.get_tasks_by_capability(
            self.tasks, AgentCapability.CAP_RUN_TESTS
        )
        
        assert len(test_tasks) == 1
        assert test_tasks[0].id == "task-3"


class TestTimelineEstimation:
    """Tests for timeline estimation."""
    
    def setup_method(self):
        """Setup test fixtures."""
        self.orchestrator = WBSOrchestratorService(organization_id="test-org")
    
    def test_get_estimated_timeline(self):
        """Test timeline estimation by phase."""
        tasks = [
            WBSTask(
                task=Task(id="task-1", name="Domain Task"),
                phase=TaskPhase.DOMAIN_MODELS,
                role=AgentRole.ARCHITECT,
                capabilities=[AgentCapability.CAP_DOMAIN_MODELING],
                estimated_hours=2.0,
            ),
            WBSTask(
                task=Task(id="task-2", name="Service Task"),
                phase=TaskPhase.DOMAIN_MODELS,
                role=AgentRole.DEVELOPER,
                capabilities=[AgentCapability.CAP_IMPLEMENTATION],
                estimated_hours=3.0,
            ),
            WBSTask(
                task=Task(id="task-3", name="Test Task"),
                phase=TaskPhase.TEST_SUITES,
                role=AgentRole.TEST_ENGINEER,
                capabilities=[AgentCapability.CAP_RUN_TESTS],
                estimated_hours=1.5,
            ),
        ]
        
        timeline = self.orchestrator.get_estimated_timeline(tasks)
        
        assert timeline[TaskPhase.DOMAIN_MODELS.name] == 5.0
        assert timeline[TaskPhase.TEST_SUITES.name] == 1.5
        assert timeline[TaskPhase.SERVICE_LAYER.name] == 0.0


class TestExecutionRequests:
    """Tests for execution request creation."""
    
    def setup_method(self):
        """Setup test fixtures."""
        self.orchestrator = WBSOrchestratorService(organization_id="test-org")
    
    def test_create_execution_requests(self):
        """Test creation of execution requests from tasks."""
        from domain.actor import Actor, ActorType
        
        actor = Actor(
            id="test-actor",
            type=ActorType.DIGITAL_EMPLOYEE,
            identity="test-actor-identity",
        )
        
        tasks = [
            WBSTask(
                task=Task(id="task-1", name="Test Task"),
                phase=TaskPhase.DOMAIN_MODELS,
                role=AgentRole.ARCHITECT,
                capabilities=[AgentCapability.CAP_DOMAIN_MODELING],
            ),
        ]
        
        requests = self.orchestrator.create_execution_requests(
            tasks, actor, "test-org"
        )
        
        assert len(requests) == 1
        request = requests[0]
        assert request.organization_id == "test-org"
        assert request.actor_id == "test-actor"
        assert request.task_type == TaskPhase.DOMAIN_MODELS.name
        assert request.capability_id == AgentCapability.CAP_DOMAIN_MODELING.value
        assert "task_id" in request.payload
    
    def test_create_execution_requests_multiple(self):
        """Test creation of multiple execution requests."""
        from domain.actor import Actor, ActorType
        
        actor = Actor(
            id="test-actor",
            type=ActorType.DIGITAL_EMPLOYEE,
            identity="test-actor-identity",
        )
        
        tasks = [
            WBSTask(
                task=Task(id="task-1", name="Task 1"),
                phase=TaskPhase.DOMAIN_MODELS,
                role=AgentRole.ARCHITECT,
                capabilities=[AgentCapability.CAP_DOMAIN_MODELING],
            ),
            WBSTask(
                task=Task(id="task-2", name="Task 2"),
                phase=TaskPhase.SERVICE_LAYER,
                role=AgentRole.DEVELOPER,
                capabilities=[AgentCapability.CAP_IMPLEMENTATION],
            ),
        ]
        
        requests = self.orchestrator.create_execution_requests(
            tasks, actor, "test-org"
        )
        
        assert len(requests) == 2
        assert {r.task_type for r in requests} == {
            TaskPhase.DOMAIN_MODELS.name,
            TaskPhase.SERVICE_LAYER.name,
        }


class TestContractIntegration:
    """Integration tests with ArchitectureContractV1."""
    
    def setup_method(self):
        """Setup test fixtures."""
        self.orchestrator = WBSOrchestratorService(organization_id="test-org")
        
    def _create_hexagonal_contract(self):
        """Create a valid hexagonal architecture contract."""
        return ArchitectureContractV1(
            schema_version="1.0",
            contract_id="hexagonal-contract",
            version="1.0.0",
            status="draft",
            project_name="hexagonal-project",
            style="hexagonal",
            language="python",
            layers=(
                LayerV1(id="domain", path="src/domain", description="Domain layer"),
                LayerV1(id="application", path="src/application", description="Application layer"),
                LayerV1(id="ports", path="src/ports", description="Ports layer"),
                LayerV1(id="adapters", path="src/adapters", description="Adapters layer"),
            ),
            dependency_rules=(
                DependencyRuleV1(
                    id="DEP-001",
                    source="application",
                    may_depend_on=("domain",),
                    severity="block",
                ),
                DependencyRuleV1(
                    id="DEP-002",
                    source="ports",
                    may_depend_on=("domain", "application"),
                    severity="block",
                ),
            ),
            quality_gates=(
                QualityGateV1(id="gate-1", type="architecture_tests", required=True),
            ),
            constraints=(),
            decisions=(),
            traceability=(),
            technology_constraints=(),
            exceptions=(),
        )
    
    def test_hexagonal_architecture_contract(self):
        """Test WBS generation for a hexagonal architecture contract."""
        contract = self._create_hexagonal_contract()
        
        tasks, task_map = self.orchestrator.generate_from_contract(contract)
        
        # Should generate tasks for all layers
        assert len(tasks) > 0
        
        # Check that domain layer tasks exist
        domain_tasks = self.orchestrator.get_tasks_by_phase(
            tasks, TaskPhase.DOMAIN_MODELS
        )
        assert len(domain_tasks) > 0
        
        # Check that service layer tasks exist
        service_tasks = self.orchestrator.get_tasks_by_phase(
            tasks, TaskPhase.SERVICE_LAYER
        )
        assert len(service_tasks) > 0
        
        # Check that API endpoint tasks exist
        api_tasks = self.orchestrator.get_tasks_by_phase(
            tasks, TaskPhase.API_ENDPOINTS
        )
        assert len(api_tasks) > 0
    
    def test_layered_architecture_contract(self):
        """Test WBS generation for a layered architecture contract."""
        contract = ArchitectureContractV1(
            schema_version="1.0",
            contract_id="layered-contract",
            version="1.0.0",
            status="draft",
            project_name="layered-project",
            style="layered",
            language="python",
            layers=(
                LayerV1(id="presentation", path="src/presentation"),
                LayerV1(id="business", path="src/business"),
                LayerV1(id="data", path="src/data"),
            ),
            dependency_rules=(
                DependencyRuleV1(
                    id="DEP-001",
                    source="business",
                    may_depend_on=("data",),
                    severity="block",
                ),
            ),
            quality_gates=(
                QualityGateV1(id="gate-1", type="architecture_tests", required=True),
            ),
            constraints=(),
            decisions=(),
            traceability=(),
            technology_constraints=(),
            exceptions=(),
        )
        
        tasks, task_map = self.orchestrator.generate_from_contract(contract)
        
        # Should generate tasks for the layers
        assert len(tasks) > 0
        
        # Validate DAG
        assert self.orchestrator.validate_dag(tasks) is True
        
        # Get execution order
        ordered = self.orchestrator.get_execution_order(tasks)
        assert len(ordered) == len(tasks)


class TestEdgeCases:
    """Tests for edge cases and error handling."""
    
    def setup_method(self):
        """Setup test fixtures."""
        self.orchestrator = WBSOrchestratorService(organization_id="test-org")
    
    def test_get_execution_order_empty(self):
        """Test execution order with empty task list."""
        ordered = self.orchestrator.get_execution_order([])
        assert ordered == []
    
    def test_validate_dag_empty(self):
        """Test DAG validation with empty task list."""
        assert self.orchestrator.validate_dag([]) is True
    
    def test_get_estimated_timeline_empty(self):
        """Test timeline estimation with empty task list."""
        timeline = self.orchestrator.get_estimated_timeline([])
        
        # Should return all phases with 0 hours
        assert all(hours == 0.0 for hours in timeline.values())
