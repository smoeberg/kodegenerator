# templates/bug_fix.py
from domain.workflow_template import WorkflowTemplate
from domain.workflow import WorkflowState, State, Transition, Gate
from domain.task import TaskPriority

bug_fix_template = WorkflowTemplate(
    id="bug_fix",
    name="Bug Fix",
    description="Workflow for reparation af bugs.",
    required_capabilities=["python", "debugging", "testing"],
    default_priority=TaskPriority.CRITICAL,
    states=[
        State(id="new", name=WorkflowState.NEW, description="Bug rapporteret, workflow endnu ikke startet."),
        State(id="triage", name=WorkflowState.ANALYSIS, description="Klassificering af bug (severity, prioritet)."),
        State(id="reproduce", name=WorkflowState.DESIGN, description="Reproducer bug for at bekræfte problemet."),
        State(id="fix", name=WorkflowState.IMPLEMENTATION, description="Implementer fix for bug."),
        State(id="test", name=WorkflowState.REVIEW, description="Test fix for at sikre, at bug er løst."),
        State(id="approved", name=WorkflowState.APPROVED, description="Godkendt af QA."),
        State(id="released", name=WorkflowState.RELEASED, description="Fix udgivet til production."),
        State(id="rejected", name=WorkflowState.REJECTED, description="Fix afvist (kan genåbnes)."),
        State(id="archived", name=WorkflowState.ARCHIVED, description="Arkiveret.")
    ],
    transitions=[
        Transition(from_state="new", to_state="triage"),
        Transition(from_state="triage", to_state="reproduce"),
        Transition(from_state="reproduce", to_state="fix"),
        Transition(
            from_state="fix",
            to_state="test",
            gate="qa_gate"
        ),
        Transition(
            from_state="test",
            to_state="approved",
            condition="all_tests_passed"
        ),
        Transition(
            from_state="test",
            to_state="rejected",
            condition="not all_tests_passed"
        ),
        Transition(
            from_state="approved",
            to_state="released"
        ),
        Transition(
            from_state="rejected",
            to_state="fix"
        ),
        Transition(
            from_state="released",
            to_state="archived"
        )
    ],
    gates=[
        Gate(
            id="qa_gate",
            name="QA Gate",
            required_approvals=["qa"],
            min_consensus_score=100,
            conditions={"all_tests_passed": True}
        )
    ],
    default_tasks=[
        {
            "id": "triage_task",
            "name": "Klassificer Bug",
            "description": "Vurder severity og prioritet af bug.",
            "priority": TaskPriority.CRITICAL,
            "dependencies": [],
            "metadata": {"estimated_hours": 1}
        },
        {
            "id": "reproduce_task",
            "name": "Reproducer Bug",
            "description": "Reproducer bug for at bekræfte problemet.",
            "priority": TaskPriority.CRITICAL,
            "dependencies": ["triage_task"],
            "metadata": {"estimated_hours": 2}
        },
        {
            "id": "fix_task",
            "name": "Implementer Fix",
            "description": "Implementer en fix for bug.",
            "priority": TaskPriority.CRITICAL,
            "dependencies": ["reproduce_task"],
            "metadata": {"estimated_hours": 4}
        },
        {
            "id": "test_task",
            "name": "Test Fix",
            "description": "Test fix for at sikre, at bug er løst.",
            "priority": TaskPriority.HIGH,
            "dependencies": ["fix_task"],
            "metadata": {"estimated_hours": 2, "required_tests": ["unit", "integration"]}
        }
    ]
)
