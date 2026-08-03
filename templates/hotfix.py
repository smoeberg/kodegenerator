# templates/hotfix.py
from domain.workflow_template import WorkflowTemplate
from domain.workflow import WorkflowState, State, Transition, Gate
from domain.task import TaskPriority

hotfix_template = WorkflowTemplate(
    id="hotfix",
    name="Hotfix",
    description="Workflow for kritiske rettelser, der skal deployes hurtigt.",
    required_capabilities=["python", "debugging", "testing", "deployment"],
    default_priority=TaskPriority.CRITICAL,
    states=[
        State(id="new", name=WorkflowState.NEW, description="Hotfix anmodet."),
        State(id="triage", name=WorkflowState.ANALYSIS, description="Vurdering af hotfix (impact, risiko)."),
        State(id="fix", name=WorkflowState.IMPLEMENTATION, description="Implementering af hotfix."),
        State(id="test", name=WorkflowState.REVIEW, description="Test af hotfix."),
        State(id="approve", name=WorkflowState.APPROVED, description="Godkendelse af hotfix."),
        State(id="deploy", name=WorkflowState.RELEASED, description="Deployment af hotfix."),
        State(id="verify", name=WorkflowState.RELEASED, description="Verificering af deployment."),
        State(id="archived", name=WorkflowState.ARCHIVED, description="Arkiveret.")
    ],
    transitions=[
        Transition(from_state="new", to_state="triage"),
        Transition(from_state="triage", to_state="fix"),
        Transition(
            from_state="fix",
            to_state="test",
            gate="test_gate"
        ),
        Transition(
            from_state="test",
            to_state="approve",
            gate="approval_gate"
        ),
        Transition(
            from_state="approve",
            to_state="deploy"
        ),
        Transition(
            from_state="deploy",
            to_state="verify"
        ),
        Transition(
            from_state="verify",
            to_state="archived"
        )
    ],
    gates=[
        Gate(
            id="test_gate",
            name="Test Gate",
            required_approvals=["qa"],
            min_consensus_score=100,
            conditions={"all_tests_passed": True, "test_coverage": 0.8}
        ),
        Gate(
            id="approval_gate",
            name="Approval Gate",
            required_approvals=["architecture_reviewer", "security_reviewer", "qa"],
            min_consensus_score=100
        )
    ],
    default_tasks=[
        {
            "id": "triage_task",
            "name": "Vurder Hotfix",
            "description": "Vurder impact og risiko af hotfix.",
            "priority": TaskPriority.CRITICAL,
            "dependencies": [],
            "metadata": {"estimated_hours": 1, "max_risk": "high"}
        },
        {
            "id": "fix_task",
            "name": "Implementer Hotfix",
            "description": "Implementer en hurtig fix for det kritiske problem.",
            "priority": TaskPriority.CRITICAL,
            "dependencies": ["triage_task"],
            "metadata": {"estimated_hours": 2, "max_complexity": "low"}
        },
        {
            "id": "test_task",
            "name": "Test Hotfix",
            "description": "Test hotfix for at sikre, at problemet er løst.",
            "priority": TaskPriority.CRITICAL,
            "dependencies": ["fix_task"],
            "metadata": {"estimated_hours": 1, "required_tests": ["unit", "smoke"]}
        },
        {
            "id": "deploy_task",
            "name": "Deploy Hotfix",
            "description": "Deploy hotfix til production.",
            "priority": TaskPriority.CRITICAL,
            "dependencies": ["test_task"],
            "metadata": {"estimated_hours": 0.5, "environment": "production"}
        },
        {
            "id": "verify_task",
            "name": "Verificer Hotfix",
            "description": "Verificer, at hotfix virker i production.",
            "priority": TaskPriority.CRITICAL,
            "dependencies": ["deploy_task"],
            "metadata": {"estimated_hours": 1}
        }
    ]
)
