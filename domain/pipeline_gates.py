# domain/pipeline_gates.py

from domain.workflow import Gate

def get_pipeline_gates() -> list[Gate]:
    """Get all gates for the software factory pipeline"""
    
    return [
        Gate(
            id="gate_requirements_approval",
            name="Requirements Approval",
            description="Human approves requirements specification",
            decision_id=None,  # Set dynamically when created
        ),
        Gate(
            id="gate_architecture_approval",
            name="Architecture Approval",
            description="Human approves system architecture",
            decision_id=None,
        ),
        Gate(
            id="gate_contracts_approval",
            name="Contracts Approval",
            description="Human approves API and data contracts",
            decision_id=None,
        ),
        Gate(
            id="gate_release_approval",
            name="Release Approval",
            description="Human approves final release",
            decision_id=None,
        ),
    ]
