# templates/security_review.py
from domain.workflow_template import WorkflowTemplate
from domain.workflow import WorkflowState, State, Transition, Gate
from domain.task import TaskPriority

security_review_template = WorkflowTemplate(
    id="security_review",
    name="Security Review",
    description="Workflow for sikkerhedsreview af kode eller systemer.",
    required_capabilities=["security", "python", "auditing"],
    default_priority=TaskPriority.HIGH,
    states=[
        State(id="new", name=WorkflowState.NEW, description="Sikkerhedsreview anmodet."),
        State(id="scan", name=WorkflowState.ANALYSIS, description="Automatisk scanning for sårbarheder."),
        State(id="manual_review", name=WorkflowState.DESIGN, description="Manuel review af sikkerhedsaspekter."),
        State(id="remediation", name=WorkflowState.IMPLEMENTATION, description="Rettelse af fundne sårbarheder."),
        State(id="verification", name=WorkflowState.REVIEW, description="Verificering af rettelser."),
        State(id="approved", name=WorkflowState.APPROVED, description="Godkendt af Security Board."),
        State(id="rejected", name=WorkflowState.REJECTED, description="Afvist (kræver omarbejdning)."),
        State(id="archived", name=WorkflowState.ARCHIVED, description="Arkiveret.")
    ],
    transitions=[
        Transition(from_state="new", to_state="scan"),
        Transition(from_state="scan", to_state="manual_review"),
        Transition(
            from_state="manual_review",
            to_state="remediation",
            condition="vulnerabilities_found"
        ),
        Transition(
            from_state="manual_review",
            to_state="approved",
            condition="no_vulnerabilities_found"
        ),
        Transition(
            from_state="remediation",
            to_state="verification"
        ),
        Transition(
            from_state="verification",
            to_state="approved",
            gate="security_gate"
        ),
        Transition(
            from_state="verification",
            to_state="remediation",
            condition="vulnerabilities_still_exist"
        ),
        Transition(
            from_state="approved",
            to_state="archived"
        ),
        Transition(
            from_state="rejected",
            to_state="manual_review"
        )
    ],
    gates=[
        Gate(
            id="security_gate",
            name="Security Gate",
            required_approvals=["security_reviewer"],
            min_consensus_score=100,
            conditions={"no_critical_vulnerabilities": True}
        )
    ],
    default_tasks=[
        {
            "id": "scan_task",
            "name": "Automatisk Scanning",
            "description": "Kør automatiske sikkerhedsscans (Bandit, Semgrep, etc.).",
            "priority": TaskPriority.HIGH,
            "dependencies": [],
            "metadata": {"tools": ["bandit", "semgrep"], "estimated_hours": 1}
        },
        {
            "id": "manual_review_task",
            "name": "Manuel Sikkerhedsreview",
            "description": "Manuel review af kode for sikkerhedsproblemer.",
            "priority": TaskPriority.HIGH,
            "dependencies": ["scan_task"],
            "metadata": {"estimated_hours": 4, "checklist": ["auth", "input_validation", "data_storage"]}
        },
        {
            "id": "remediation_task",
            "name": "Rettelse af Sårbarheder",
            "description": "Rettelse af fundne sårbarheder.",
            "priority": TaskPriority.CRITICAL,
            "dependencies": ["manual_review_task"],
            "metadata": {"estimated_hours": 8}
        },
        {
            "id": "verification_task",
            "name": "Verificering af Rettelser",
            "description": "Verificer, at sårbarhederne er rettet.",
            "priority": TaskPriority.HIGH,
            "dependencies": ["remediation_task"],
            "metadata": {"estimated_hours": 2}
        }
    ]
)
