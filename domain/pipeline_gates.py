# domain/pipeline_gates.py

from domain.workflow import Gate

def get_pipeline_gates() -> list[Gate]:
    """Get all gates for the software factory pipeline"""
    
    return [
        Gate(
            id="gate_requirements_approval",
            name="Requirements Approval",
        ),
        Gate(
            id="gate_architecture_approval",
            name="Architecture Approval",
        ),
        Gate(
            id="gate_contracts_approval",
            name="Contracts Approval",
        ),
        Gate(
            id="gate_release_approval",
            name="Release Approval",
        ),
    ]
