# templates/deployment.py
from domain.workflow_template import WorkflowTemplate
from domain.workflow import WorkflowState, State, Transition, Gate
from domain.task import TaskPriority

deployment_template = WorkflowTemplate(
    id="deployment",
    name="Deployment",
    description="Workflow for deployment af kode til production.",
    required_capabilities=["deployment", "ci_cd", "testing"],
    default_priority=TaskPriority.CRITICAL,
    states=[
        State(id="new", name=WorkflowState.NEW, description="Deployment anmodet."),
        State(id="build", name=WorkflowState.ANALYSIS, description="Bygning af artefakter."),
        State(id="test", name=WorkflowState.DESIGN, description="Test af bygget kode."),
        State(id="staging", name=WorkflowState.IMPLEMENTATION, description="Deployment til staging."),
        State(id="verify", name=WorkflowState.REVIEW, description="Verificering af staging."),
        State(id="production", name=WorkflowState.RELEASED, description="Deployment til production."),
        State(id="rejected", name=WorkflowState.REJECTED, description="Deployment afvist."),
        State(id="archived", name=WorkflowState.ARCHIVED, description="Arkiveret.")
    ],
    transitions=[
        Transition(from_state="new", to_state="build"),
        Transition(from_state="build", to_state="test"),
        Transition(
            from_state="test",
            to_state="staging",
            gate="test_gate"
        ),
        Transition(
            from_state="staging",
            to_state="verify",
            gate="staging_gate"
        ),
        Transition(
            from_state="verify",
            to_state="production",
            gate="production_gate"
        ),
        Transition(
            from_state="production",
            to_state="archived"
        ),
        Transition(
            from_state="rejected",
            to_state="new"
        )
    ],
    gates=[
        Gate(
            id="test_gate",
            name="Test Gate",
            required_approvals=["qa"],
            min_consensus_score=100,
            conditions={"all_tests_passed": True, "test_coverage": 0.95}
        ),
        Gate(
            id="staging_gate",
            name="Staging Gate",
            required_approvals=["qa", "architecture_reviewer"],
            min_consensus_score=100
        ),
        Gate(
            id="production_gate",
            name="Production Gate",
            required_approvals=["qa", "architecture_reviewer", "security_reviewer"],
            min_consensus_score=100
        )
    ],
    default_tasks=[
        {
            "id": "build_task",
            "name": "Byg Artefakter",
            "description": "Byg alle nødvendige artefakter (Docker images, binaries, etc.).",
            "priority": TaskPriority.CRITICAL,
            "dependencies": [],
            "metadata": {"estimated_hours": 2, "tools": ["docker", "make"]}
        },
        {
            "id": "test_task",
            "name": "Test Bygget Kode",
            "description": "Kør alle tests på bygget kode.",
            "priority": TaskPriority.CRITICAL,
            "dependencies": ["build_task"],
            "metadata": {"estimated_hours": 1, "required_coverage": 0.95}
        },
        {
            "id": "staging_task",
            "name": "Deploy til Staging",
            "description": "Deploy bygget kode til staging-miljø.",
            "priority": TaskPriority.CRITICAL,
            "dependencies": ["test_task"],
            "metadata": {"estimated_hours": 0.5, "environment": "staging"}
        },
        {
            "id": "verify_task",
            "name": "Verificer Staging",
            "description": "Verificer, at staging-deployment fungerer korrekt.",
            "priority": TaskPriority.HIGH,
            "dependencies": ["staging_task"],
            "metadata": {"estimated_hours": 1, "checklist": ["smoke tests", "performance tests"]}
        },
        {
            "id": "production_task",
            "name": "Deploy til Production",
            "description": "Deploy bygget kode til production-miljø.",
            "priority": TaskPriority.CRITICAL,
            "dependencies": ["verify_task"],
            "metadata": {"estimated_hours": 0.5, "environment": "production"}
        }
    ]
)
