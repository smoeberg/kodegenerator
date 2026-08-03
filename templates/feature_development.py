# templates/feature_development.py
from domain.workflow_template import WorkflowTemplate
from domain.workflow import WorkflowState, State, Transition, Gate
from domain.task import TaskPriority

feature_development_template = WorkflowTemplate(
    id="feature_development",
    name="Feature Development",
    description="Standard workflow for udvikling af nye features.",
    required_capabilities=["python", "design", "testing"],
    default_priority=TaskPriority.HIGH,
    states=[
        State(id="new", name=WorkflowState.NEW, description="Intent oprettet, workflow endnu ikke startet."),
        State(id="analysis", name=WorkflowState.ANALYSIS, description="Analyse af krav og specifikationer."),
        State(id="design", name=WorkflowState.DESIGN, description="Design af arkitektur og løsning."),
        State(id="implementation", name=WorkflowState.IMPLEMENTATION, description="Implementering af kode."),
        State(id="review", name=WorkflowState.REVIEW, description="Review af kode, tests og dokumentation."),
        State(id="approved", name=WorkflowState.APPROVED, description="Godkendt af alle nødvendige boards."),
        State(id="released", name=WorkflowState.RELEASED, description="Udgivet til production."),
        State(id="rejected", name=WorkflowState.REJECTED, description="Afvist (kan genåbnes)."),
        State(id="archived", name=WorkflowState.ARCHIVED, description="Arkiveret.")
    ],
    transitions=[
        Transition(from_state="new", to_state="analysis"),
        Transition(from_state="analysis", to_state="design"),
        Transition(from_state="design", to_state="implementation"),
        Transition(
            from_state="implementation",
            to_state="review",
            gate="review_gate"
        ),
        Transition(
            from_state="review",
            to_state="approved",
            condition="consensus_score >= 80"
        ),
        Transition(
            from_state="review",
            to_state="rejected",
            condition="consensus_score < 50"
        ),
        Transition(
            from_state="approved",
            to_state="released"
        ),
        Transition(
            from_state="rejected",
            to_state="new"
        ),
        Transition(
            from_state="released",
            to_state="archived"
        ),
        Transition(
            from_state="approved",
            to_state="archived"
        )
    ],
    gates=[
        Gate(
            id="review_gate",
            name="Review Gate",
            required_approvals=["architecture_reviewer", "qa", "security_reviewer"],
            min_consensus_score=80,
            conditions={"test_coverage": 0.9}
        )
    ],
    default_tasks=[
        {
            "id": "analysis_task",
            "name": "Analyse Krav",
            "description": "Analyser brugerkrav og specifikationer.",
            "priority": TaskPriority.HIGH,
            "dependencies": [],
            "metadata": {"estimated_hours": 2}
        },
        {
            "id": "design_task",
            "name": "Design Løsning",
            "description": "Design arkitektur og løsning for featuret.",
            "priority": TaskPriority.HIGH,
            "dependencies": ["analysis_task"],
            "metadata": {"estimated_hours": 4}
        },
        {
            "id": "implementation_task",
            "name": "Implementer Kode",
            "description": "Implementer kode for featuret.",
            "priority": TaskPriority.HIGH,
            "dependencies": ["design_task"],
            "metadata": {"estimated_hours": 8}
        },
        {
            "id": "test_task",
            "name": "Skriv Tests",
            "description": "Skriv unit tests og integration tests.",
            "priority": TaskPriority.MEDIUM,
            "dependencies": ["implementation_task"],
            "metadata": {"estimated_hours": 4, "required_coverage": 0.9}
        },
        {
            "id": "documentation_task",
            "name": "Skriv Dokumentation",
            "description": "Skriv dokumentation for featuret.",
            "priority": TaskPriority.LOW,
            "dependencies": ["implementation_task"],
            "metadata": {"estimated_hours": 2}
        }
    ]
)
