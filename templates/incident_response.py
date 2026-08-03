# templates/incident_response.py
from domain.workflow_template import WorkflowTemplate
from domain.workflow import WorkflowState, State, Transition, Gate
from domain.task import TaskPriority

incident_response_template = WorkflowTemplate(
    id="incident_response",
    name="Incident Response",
    description="Workflow for håndtering af incidents (fejl, sikkerhedsbrud, etc.).",
    required_capabilities=["incident_response", "debugging", "communication"],
    default_priority=TaskPriority.CRITICAL,
    states=[
        State(id="new", name=WorkflowState.NEW, description="Incident rapporteret."),
        State(id="triage", name=WorkflowState.ANALYSIS, description="Klassificering af incident (severity, impact)."),
        State(id="investigate", name=WorkflowState.DESIGN, description="Undersøgelse af incident (root cause analysis)."),
        State(id="mitigate", name=WorkflowState.IMPLEMENTATION, description="Midlertidig løsning (hvis muligt)."),
        State(id="resolve", name=WorkflowState.REVIEW, description="Permanent løsning og verificering."),
        State(id="postmortem", name=WorkflowState.APPROVED, description="Postmortem analyse og dokumentation."),
        State(id="archived", name=WorkflowState.ARCHIVED, description="Arkiveret.")
    ],
    transitions=[
        Transition(from_state="new", to_state="triage"),
        Transition(from_state="triage", to_state="investigate"),
        Transition(from_state="investigate", to_state="mitigate"),
        Transition(
            from_state="mitigate",
            to_state="resolve",
            condition="mitigation_successful"
        ),
        Transition(
            from_state="resolve",
            to_state="postmortem",
            gate="resolution_gate"
        ),
        Transition(
            from_state="postmortem",
            to_state="archived"
        )
    ],
    gates=[
        Gate(
            id="resolution_gate",
            name="Resolution Gate",
            required_approvals=["incident_commander", "qa"],
            min_consensus_score=100,
            conditions={"incident_resolved": True}
        )
    ],
    default_tasks=[
        {
            "id": "triage_task",
            "name": "Klassificer Incident",
            "description": "Vurder severity, impact og prioritet af incident.",
            "priority": TaskPriority.CRITICAL,
            "dependencies": [],
            "metadata": {"estimated_hours": 0.5, "severity_levels": ["low", "medium", "high", "critical"]}
        },
        {
            "id": "investigate_task",
            "name": "Undersøg Incident",
            "description": "Find root cause af incident (logs, metrics, etc.).",
            "priority": TaskPriority.CRITICAL,
            "dependencies": ["triage_task"],
            "metadata": {"estimated_hours": 2, "tools": ["logs", "metrics", "tracing"]}
        },
        {
            "id": "mitigate_task",
            "name": "Midlertidig Løsning",
            "description": "Implementer en midlertidig løsning (hvis muligt).",
            "priority": TaskPriority.CRITICAL,
            "dependencies": ["investigate_task"],
            "metadata": {"estimated_hours": 1, "required_approval": "incident_commander"}
        },
        {
            "id": "resolve_task",
            "name": "Permanent Løsning",
            "description": "Implementer en permanent løsning og verificer.",
            "priority": TaskPriority.HIGH,
            "dependencies": ["mitigate_task"],
            "metadata": {"estimated_hours": 4, "required_tests": ["unit", "integration"]}
        },
        {
            "id": "postmortem_task",
            "name": "Postmortem Analyse",
            "description": "Dokumenter incident, root cause, og forebyggende foranstaltninger.",
            "priority": TaskPriority.HIGH,
            "dependencies": ["resolve_task"],
            "metadata": {"estimated_hours": 2, "output": "Incident Report"}
        }
    ]
)
