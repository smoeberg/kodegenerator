"""
WBS Orchestrator Service

Work Breakdown Structure (WBS) & Task Dependency Orchestrator

Tager en godkendt ArchitectureContract og nedbryder den til en komplet
række konkrete Task og TaskExecution-enheder, struktureret i en Directed
Acyclic Graph (DAG) med korrekte afhængigheder.

Faser:
1. Domain/Datamodeller
2. Service-lag & Forretningslogik
3. API Endpoints / Grænseflader
4. Testsuiter & Sandbox Verification Cases
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple, TYPE_CHECKING
from enum import Enum, auto
import uuid
from datetime import datetime, timezone

from domain.task import Task, TaskStatus, TaskPriority, DependencyStatus
from domain.task_execution import TaskExecutionRequest, TaskExecutionReceipt
from domain.architecture_contract_v1 import ArchitectureContractV1, LayerV1
from domain.capability import Capability
from domain.role import RoleDefinition
from domain.actor import Actor, ActorType

if TYPE_CHECKING:
    from domain.organization import Organization


class AgentRole(Enum):
    """Specialiserede agent-roller for task-tildeling."""
    DEVELOPER = auto()
    ARCHITECT = auto()
    QA = auto()
    SECURITY = auto()
    TEST_ENGINEER = auto()
    CODE_REVIEWER = auto()
    DOCUMENTATION = auto()


class AgentCapability(Enum):
    """Capability-identifikatorer for agent-roller."""
    # Arkitektur & Design
    CAP_ARCHITECTURE_DESIGN = "cap.architecture.design"
    CAP_DOMAIN_MODELING = "cap.domain.modeling"
    CAP_CONTRACT_DESIGN = "cap.contract.design"
    
    # Udvikling
    CAP_CODE_GENERATION = "cap.code.generation"
    CAP_AST_WRITE = "cap.ast.write"
    CAP_IMPLEMENTATION = "cap.implementation"
    
    # Test & Verifikation
    CAP_RUN_TESTS = "cap.run.tests"
    CAP_VERIFICATION = "cap.verification"
    CAP_SANDBOX_TESTING = "cap.sandbox.testing"
    
    # Sikkerhed
    CAP_SECURITY_AUDIT = "cap.security.audit"
    CAP_PENETRATION_TEST = "cap.penetration.test"
    
    # Dokumentation
    CAP_DOCUMENTATION = "cap.documentation"
    
    # Review
    CAP_CODE_REVIEW = "cap.code.review"


class TaskPhase(Enum):
    """Faser i WBS for struktureret udvikling."""
    DOMAIN_MODELS = auto()
    SERVICE_LAYER = auto()
    API_ENDPOINTS = auto()
    TEST_SUITES = auto()
    VERIFICATION = auto()
    DOCUMENTATION = auto()


@dataclass
class TaskTemplate:
    """Skabelon for standardiserede tasks."""
    phase: TaskPhase
    name_prefix: str
    description_template: str
    role: AgentRole
    capabilities: List[AgentCapability]
    priority: TaskPriority
    estimated_hours: float
    depends_on_phases: List[TaskPhase] = field(default_factory=list)


# Standard task skabeloner
TASK_TEMPLATES: Dict[TaskPhase, List[TaskTemplate]] = {
    TaskPhase.DOMAIN_MODELS: [
        TaskTemplate(
            phase=TaskPhase.DOMAIN_MODELS,
            name_prefix="Define Domain Entities",
            description_template="Define and model domain entities for {layer_path}",
            role=AgentRole.ARCHITECT,
            capabilities=[
                AgentCapability.CAP_DOMAIN_MODELING,
                AgentCapability.CAP_ARCHITECTURE_DESIGN,
            ],
            priority=TaskPriority.HIGH,
            estimated_hours=2.0,
        ),
        TaskTemplate(
            phase=TaskPhase.DOMAIN_MODELS,
            name_prefix="Create Value Objects",
            description_template="Create immutable value objects for {layer_path}",
            role=AgentRole.DEVELOPER,
            capabilities=[
                AgentCapability.CAP_DOMAIN_MODELING,
                AgentCapability.CAP_CODE_GENERATION,
            ],
            priority=TaskPriority.HIGH,
            estimated_hours=1.5,
        ),
        TaskTemplate(
            phase=TaskPhase.DOMAIN_MODELS,
            name_prefix="Define Domain Services",
            description_template="Define domain service interfaces for {layer_path}",
            role=AgentRole.ARCHITECT,
            capabilities=[
                AgentCapability.CAP_CONTRACT_DESIGN,
                AgentCapability.CAP_DOMAIN_MODELING,
            ],
            priority=TaskPriority.HIGH,
            estimated_hours=2.0,
        ),
    ],
    
    TaskPhase.SERVICE_LAYER: [
        TaskTemplate(
            phase=TaskPhase.SERVICE_LAYER,
            name_prefix="Implement Application Services",
            description_template="Implement application services for {layer_path}",
            role=AgentRole.DEVELOPER,
            capabilities=[
                AgentCapability.CAP_IMPLEMENTATION,
                AgentCapability.CAP_AST_WRITE,
            ],
            priority=TaskPriority.HIGH,
            estimated_hours=3.0,
            depends_on_phases=[TaskPhase.DOMAIN_MODELS],
        ),
        TaskTemplate(
            phase=TaskPhase.SERVICE_LAYER,
            name_prefix="Create Use Case Handlers",
            description_template="Create use case handlers for {layer_path}",
            role=AgentRole.DEVELOPER,
            capabilities=[
                AgentCapability.CAP_IMPLEMENTATION,
                AgentCapability.CAP_CODE_GENERATION,
            ],
            priority=TaskPriority.HIGH,
            estimated_hours=2.5,
            depends_on_phases=[TaskPhase.DOMAIN_MODELS],
        ),
        TaskTemplate(
            phase=TaskPhase.SERVICE_LAYER,
            name_prefix="Implement Business Logic",
            description_template="Implement core business logic for {layer_path}",
            role=AgentRole.DEVELOPER,
            capabilities=[
                AgentCapability.CAP_IMPLEMENTATION,
                AgentCapability.CAP_AST_WRITE,
            ],
            priority=TaskPriority.MEDIUM,
            estimated_hours=2.0,
            depends_on_phases=[TaskPhase.DOMAIN_MODELS],
        ),
    ],
    
    TaskPhase.API_ENDPOINTS: [
        TaskTemplate(
            phase=TaskPhase.API_ENDPOINTS,
            name_prefix="Design API Contracts",
            description_template="Design API contracts and OpenAPI spec for {layer_path}",
            role=AgentRole.ARCHITECT,
            capabilities=[
                AgentCapability.CAP_CONTRACT_DESIGN,
                AgentCapability.CAP_ARCHITECTURE_DESIGN,
            ],
            priority=TaskPriority.HIGH,
            estimated_hours=2.0,
            depends_on_phases=[TaskPhase.SERVICE_LAYER],
        ),
        TaskTemplate(
            phase=TaskPhase.API_ENDPOINTS,
            name_prefix="Implement API Endpoints",
            description_template="Implement REST API endpoints for {layer_path}",
            role=AgentRole.DEVELOPER,
            capabilities=[
                AgentCapability.CAP_CODE_GENERATION,
                AgentCapability.CAP_AST_WRITE,
            ],
            priority=TaskPriority.HIGH,
            estimated_hours=3.0,
            depends_on_phases=[TaskPhase.SERVICE_LAYER],
        ),
        TaskTemplate(
            phase=TaskPhase.API_ENDPOINTS,
            name_prefix="Create API Adapters",
            description_template="Create adapters for external integrations in {layer_path}",
            role=AgentRole.DEVELOPER,
            capabilities=[
                AgentCapability.CAP_IMPLEMENTATION,
                AgentCapability.CAP_AST_WRITE,
            ],
            priority=TaskPriority.MEDIUM,
            estimated_hours=2.0,
            depends_on_phases=[TaskPhase.SERVICE_LAYER],
        ),
    ],
    
    TaskPhase.TEST_SUITES: [
        TaskTemplate(
            phase=TaskPhase.TEST_SUITES,
            name_prefix="Write Unit Tests",
            description_template="Write comprehensive unit tests for {layer_path}",
            role=AgentRole.TEST_ENGINEER,
            capabilities=[
                AgentCapability.CAP_RUN_TESTS,
                AgentCapability.CAP_VERIFICATION,
            ],
            priority=TaskPriority.HIGH,
            estimated_hours=2.5,
            depends_on_phases=[TaskPhase.DOMAIN_MODELS, TaskPhase.SERVICE_LAYER],
        ),
        TaskTemplate(
            phase=TaskPhase.TEST_SUITES,
            name_prefix="Create Integration Tests",
            description_template="Create integration tests for {layer_path}",
            role=AgentRole.TEST_ENGINEER,
            capabilities=[
                AgentCapability.CAP_RUN_TESTS,
                AgentCapability.CAP_SANDBOX_TESTING,
            ],
            priority=TaskPriority.MEDIUM,
            estimated_hours=2.0,
            depends_on_phases=[TaskPhase.SERVICE_LAYER, TaskPhase.API_ENDPOINTS],
        ),
        TaskTemplate(
            phase=TaskPhase.TEST_SUITES,
            name_prefix="Implement Property Tests",
            description_template="Implement property-based tests for {layer_path}",
            role=AgentRole.TEST_ENGINEER,
            capabilities=[
                AgentCapability.CAP_RUN_TESTS,
                AgentCapability.CAP_VERIFICATION,
            ],
            priority=TaskPriority.LOW,
            estimated_hours=1.5,
            depends_on_phases=[TaskPhase.DOMAIN_MODELS],
        ),
    ],
    
    TaskPhase.VERIFICATION: [
        TaskTemplate(
            phase=TaskPhase.VERIFICATION,
            name_prefix="Security Audit",
            description_template="Perform security audit for {layer_path}",
            role=AgentRole.SECURITY,
            capabilities=[
                AgentCapability.CAP_SECURITY_AUDIT,
                AgentCapability.CAP_PENETRATION_TEST,
            ],
            priority=TaskPriority.HIGH,
            estimated_hours=2.0,
            depends_on_phases=[TaskPhase.DOMAIN_MODELS, TaskPhase.SERVICE_LAYER, TaskPhase.API_ENDPOINTS],
        ),
        TaskTemplate(
            phase=TaskPhase.VERIFICATION,
            name_prefix="Architecture Verification",
            description_template="Verify architecture compliance for {layer_path}",
            role=AgentRole.ARCHITECT,
            capabilities=[
                AgentCapability.CAP_ARCHITECTURE_DESIGN,
                AgentCapability.CAP_VERIFICATION,
            ],
            priority=TaskPriority.HIGH,
            estimated_hours=1.5,
            depends_on_phases=[TaskPhase.DOMAIN_MODELS, TaskPhase.SERVICE_LAYER, TaskPhase.API_ENDPOINTS],
        ),
        TaskTemplate(
            phase=TaskPhase.VERIFICATION,
            name_prefix="Code Review",
            description_template="Perform code review for {layer_path}",
            role=AgentRole.CODE_REVIEWER,
            capabilities=[
                AgentCapability.CAP_CODE_REVIEW,
                AgentCapability.CAP_VERIFICATION,
            ],
            priority=TaskPriority.MEDIUM,
            estimated_hours=1.0,
            depends_on_phases=[TaskPhase.SERVICE_LAYER, TaskPhase.API_ENDPOINTS],
        ),
    ],
    
    TaskPhase.DOCUMENTATION: [
        TaskTemplate(
            phase=TaskPhase.DOCUMENTATION,
            name_prefix="Generate API Documentation",
            description_template="Generate comprehensive API documentation for {layer_path}",
            role=AgentRole.DOCUMENTATION,
            capabilities=[
                AgentCapability.CAP_DOCUMENTATION,
            ],
            priority=TaskPriority.LOW,
            estimated_hours=1.5,
            depends_on_phases=[TaskPhase.API_ENDPOINTS],
        ),
        TaskTemplate(
            phase=TaskPhase.DOCUMENTATION,
            name_prefix="Create Architecture Documentation",
            description_template="Document architecture decisions for {layer_path}",
            role=AgentRole.DOCUMENTATION,
            capabilities=[
                AgentCapability.CAP_DOCUMENTATION,
            ],
            priority=TaskPriority.LOW,
            estimated_hours=1.0,
            depends_on_phases=[TaskPhase.DOMAIN_MODELS, TaskPhase.SERVICE_LAYER],
        ),
    ],
}


@dataclass
class WBSTask:
    """En udvidet Task med WBS-specifik metadata."""
    task: Task
    phase: TaskPhase
    role: AgentRole
    capabilities: List[AgentCapability]
    layer_id: Optional[str] = None
    estimated_hours: float = 1.0
    
    @property
    def id(self) -> str:
        return self.task.id
    
    @property
    def name(self) -> str:
        return self.task.name
    
    @property
    def dependencies(self) -> List[str]:
        return self.task.dependencies


class WBSOrchestratorService:
    """
    Work Breakdown Structure Orchestrator
    
    Nedbryder en ArchitectureContract til en DAG af Tasks.
    """
    
    def __init__(self, organization_id: Optional[str] = None):
        self.organization_id = organization_id
        self._task_counter: Dict[TaskPhase, int] = {}
    
    def reset_counters(self) -> None:
        """Reset task counters for fresh generation."""
        self._task_counter = {}
    
    def _get_next_sequence(self, phase: TaskPhase) -> int:
        """Get next sequence number for a phase."""
        if phase not in self._task_counter:
            self._task_counter[phase] = 0
        self._task_counter[phase] += 1
        return self._task_counter[phase]
    
    def _create_task_from_template(
        self,
        template: TaskTemplate,
        layer: Optional[LayerV1] = None,
        workflow_id: Optional[str] = None,
    ) -> WBSTask:
        """Opret en Task fra en skabelon."""
        sequence = self._get_next_sequence(template.phase)
        layer_path = layer.path if layer else "root"
        
        # Generer task navn
        if layer:
            name = f"{sequence:02d}. {template.name_prefix} ({layer.id})"
        else:
            name = f"{sequence:02d}. {template.name_prefix}"
        
        # Udskift placeholders i description
        description = template.description_template.format(layer_path=layer_path)
        
        task = Task(
            id=str(uuid.uuid4()),
            name=name,
            description=description,
            status=TaskStatus.PENDING,
            priority=template.priority,
            workflow_id=workflow_id,
            organization_id=self.organization_id,
            metadata={
                "phase": template.phase.name,
                "layer_id": layer.id if layer else None,
                "estimated_hours": template.estimated_hours,
                "role": template.role.name,
                "capabilities": [cap.value for cap in template.capabilities],
            },
        )
        
        return WBSTask(
            task=task,
            phase=template.phase,
            role=template.role,
            capabilities=template.capabilities,
            layer_id=layer.id if layer else None,
            estimated_hours=template.estimated_hours,
        )
    
    def _build_dependency_graph(
        self,
        tasks_by_phase: Dict[TaskPhase, List[WBSTask]],
    ) -> List[WBSTask]:
        """
        Byg et afhængighedsgraf ud fra faserne.
        
        Tasks i senere faser afhænger af tasks i tidligere faser.
        """
        # Definer fase-afhængigheder
        phase_order = [
            TaskPhase.DOMAIN_MODELS,
            TaskPhase.SERVICE_LAYER,
            TaskPhase.API_ENDPOINTS,
            TaskPhase.TEST_SUITES,
            TaskPhase.VERIFICATION,
            TaskPhase.DOCUMENTATION,
        ]
        
        # Opret en liste med alle tasks
        all_tasks: List[WBSTask] = []
        task_map: Dict[str, WBSTask] = {}
        
        # Først saml alle tasks
        for phase in phase_order:
            if phase in tasks_by_phase:
                for wbs_task in tasks_by_phase[phase]:
                    all_tasks.append(wbs_task)
                    task_map[wbs_task.id] = wbs_task
        
        # Derefter opret afhængigheder baseret på fase
        for i, phase in enumerate(phase_order):
            if phase in tasks_by_phase:
                for wbs_task in tasks_by_phase[phase]:
                    # Tilføj afhængigheder til tasks fra tidligere faser
                    for prev_phase in phase_order[:i]:
                        if prev_phase in tasks_by_phase:
                            # Tilføj afhængighed til alle tasks i forrige fase
                            # (i praksis ville man måske kun afhænge af specifikke tasks)
                            for prev_task in tasks_by_phase[prev_phase]:
                                if prev_task.id not in wbs_task.task.dependencies:
                                    wbs_task.task.dependencies.append(prev_task.id)
        
        return all_tasks
    
    def generate_from_contract(
        self,
        contract: ArchitectureContractV1,
        workflow_id: Optional[str] = None,
    ) -> Tuple[List[WBSTask], Dict[str, WBSTask]]:
        """
        Generer en komplet WBS fra en ArchitectureContract.
        
        Args:
            contract: Den godkendte arkitekturkontrakt
            workflow_id: Optional workflow ID
            
        Returns:
            Tuple med (liste af WBSTasks, dictionary med task ID -> WBSTask)
        """
        self.reset_counters()
        
        # Opret tasks for hver layer i kontrakten
        tasks_by_phase: Dict[TaskPhase, List[WBSTask]] = {}
        
        # Håndter hver layer
        for layer in contract.layers:
            # Phase 1: Domain/Datamodeller
            if layer.id.startswith("domain") or "domain" in layer.path.lower():
                if TaskPhase.DOMAIN_MODELS not in tasks_by_phase:
                    tasks_by_phase[TaskPhase.DOMAIN_MODELS] = []
                for template in TASK_TEMPLATES[TaskPhase.DOMAIN_MODELS]:
                    tasks_by_phase[TaskPhase.DOMAIN_MODELS].append(
                        self._create_task_from_template(template, layer, workflow_id)
                    )
            
            # Phase 2: Service-lag
            if layer.id.startswith("application") or "application" in layer.path.lower() or "service" in layer.path.lower():
                if TaskPhase.SERVICE_LAYER not in tasks_by_phase:
                    tasks_by_phase[TaskPhase.SERVICE_LAYER] = []
                for template in TASK_TEMPLATES[TaskPhase.SERVICE_LAYER]:
                    tasks_by_phase[TaskPhase.SERVICE_LAYER].append(
                        self._create_task_from_template(template, layer, workflow_id)
                    )
            
            # Phase 3: API Endpoints
            if layer.id.startswith("ports") or layer.id.startswith("adapters") or "api" in layer.path.lower():
                if TaskPhase.API_ENDPOINTS not in tasks_by_phase:
                    tasks_by_phase[TaskPhase.API_ENDPOINTS] = []
                for template in TASK_TEMPLATES[TaskPhase.API_ENDPOINTS]:
                    tasks_by_phase[TaskPhase.API_ENDPOINTS].append(
                        self._create_task_from_template(template, layer, workflow_id)
                    )
        
        # Tilføj standard test og verification tasks
        for phase in [TaskPhase.TEST_SUITES, TaskPhase.VERIFICATION, TaskPhase.DOCUMENTATION]:
            if phase not in tasks_by_phase:
                tasks_by_phase[phase] = []
            for template in TASK_TEMPLATES[phase]:
                tasks_by_phase[phase].append(
                    self._create_task_from_template(template, None, workflow_id)
                )
        
        # Byg afhængighedsgraf
        all_tasks = self._build_dependency_graph(tasks_by_phase)
        
        # Opret task map
        task_map = {task.id: task for task in all_tasks}
        
        return all_tasks, task_map
    
    def validate_dag(self, tasks: List[WBSTask]) -> bool:
        """
        Valider at task-grafen er en gyldig DAG (ingen cirkulære afhængigheder).
        
        Args:
            tasks: Liste af WBSTasks
            
        Returns:
            bool: True hvis grafen er en gyldig DAG
            
        Raises:
            ValueError: Hvis der findes cirkulære afhængigheder
        """
        visited = set()
        recursion_stack = set()
        task_map = {task.id: task for task in tasks}
        
        def has_cycle(task_id: str) -> bool:
            visited.add(task_id)
            recursion_stack.add(task_id)
            
            for dep_id in task_map[task_id].task.dependencies:
                if dep_id not in task_map:
                    # Afhængighed til ukendt task - dette er en fejl
                    raise ValueError(f"Task {task_id} has dependency on unknown task {dep_id}")
                
                if dep_id not in visited:
                    if has_cycle(dep_id):
                        return True
                elif dep_id in recursion_stack:
                    return True
            
            recursion_stack.remove(task_id)
            return False
        
        for task in tasks:
            if task.id not in visited:
                if has_cycle(task.id):
                    return False
        
        return True
    
    def get_execution_order(self, tasks: List[WBSTask]) -> List[WBSTask]:
        """
        Returner tasks i korrekt eksekveringsrækkefølge (topologisk sortering).
        
        Args:
            tasks: Liste af WBSTasks
            
        Returns:
            Liste af tasks sorteret i eksekveringsrækkefølge
        """
        if not tasks:
            return []
        
        # Byg afhængighedsgraf
        task_map = {task.id: task for task in tasks}
        in_degree = {task.id: 0 for task in tasks}
        
        # Beregn ind-grad for hver node
        for task in tasks:
            for dep_id in task.task.dependencies:
                if dep_id in in_degree:
                    in_degree[task.id] += 1
        
        # Find alle nodes med ind-grad 0
        queue = [task for task in tasks if in_degree[task.id] == 0]
        result = []
        
        # Topologisk sortering (Kahn's algorithm)
        while queue:
            # Sorter efter prioritet (højeste først)
            queue.sort(key=lambda t: t.task.priority.value, reverse=True)
            current = queue.pop(0)
            result.append(current)
            
            # Opdater ind-grad for afhængige tasks
            for task in tasks:
                if current.id in task.task.dependencies:
                    in_degree[task.id] -= 1
                    if in_degree[task.id] == 0:
                        queue.append(task)
        
        # Tjek for cyklusser
        if len(result) != len(tasks):
            raise ValueError("Cycle detected in task dependencies - cannot determine execution order")
        
        return result
    
    def create_execution_requests(
        self,
        tasks: List[WBSTask],
        actor: Actor,
        organization_id: str,
    ) -> List[TaskExecutionRequest]:
        """
        Opret TaskExecutionRequest-objekter for en liste af tasks.
        
        Args:
            tasks: Liste af WBSTasks
            actor: Den udfølgende actor
            organization_id: Organisations-ID
            
        Returns:
            Liste af TaskExecutionRequest-objekter
        """
        requests = []
        
        for task in tasks:
            # Bestem capability baseret på taskens rolle
            primary_capability = task.capabilities[0].value if task.capabilities else ""
            
            request = TaskExecutionRequest(
                execution_id=str(uuid.uuid4()),
                organization_id=organization_id,
                actor_id=actor.id,
                task_type=task.phase.name,
                capability_id=primary_capability,
                payload={
                    "task_id": task.id,
                    "task_name": task.name,
                    "phase": task.phase.name,
                    "layer_id": task.layer_id,
                    "description": task.task.description,
                },
            )
            requests.append(request)
        
        return requests
    
    def get_tasks_by_role(self, tasks: List[WBSTask], role: AgentRole) -> List[WBSTask]:
        """Filtrer tasks efter rolle."""
        return [task for task in tasks if task.role == role]
    
    def get_tasks_by_phase(self, tasks: List[WBSTask], phase: TaskPhase) -> List[WBSTask]:
        """Filtrer tasks efter fase."""
        return [task for task in tasks if task.phase == phase]
    
    def get_tasks_by_capability(
        self, tasks: List[WBSTask], capability: AgentCapability
    ) -> List[WBSTask]:
        """Filtrer tasks efter capability."""
        return [task for task in tasks if capability in task.capabilities]
    
    def get_estimated_timeline(self, tasks: List[WBSTask]) -> Dict[str, float]:
        """
        Beregn estimeret tidsforbrug pr. fase.
        
        Args:
            tasks: Liste af WBSTasks
            
        Returns:
            Dictionary med fase -> total estimeret timer
        """
        timeline = {phase.name: 0.0 for phase in TaskPhase}
        
        for task in tasks:
            timeline[task.phase.name] += task.estimated_hours
        
        return timeline
