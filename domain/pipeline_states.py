# domain/pipeline_states.py

from enum import Enum

class PipelineState(str, Enum):
    """Software factory pipeline states"""
    
    # ===== Requirements phase =====
    REQUIREMENTS_DRAFT = "requirements_draft"
    REQUIREMENTS_VALIDATED = "requirements_validated"
    REQUIREMENTS_APPROVED = "requirements_approved"
    
    # ===== Architecture phase =====
    ARCHITECTURE_GENERATING = "architecture_generating"
    ARCHITECTURE_GENERATED = "architecture_generated"
    ARCHITECTURE_APPROVED = "architecture_approved"
    
    # ===== Contracts phase =====
    CONTRACTS_GENERATING = "contracts_generating"
    CONTRACTS_GENERATED = "contracts_generated"
    CONTRACTS_APPROVED = "contracts_approved"
    
    # ===== Code phase =====
    CODE_GENERATING = "code_generating"
    CODE_GENERATED = "code_generated"
    
    # ===== Tests phase =====
    TESTS_GENERATING = "tests_generating"
    TESTS_GENERATED = "tests_generated"
    TESTS_RUNNING = "tests_running"
    TESTS_PASSED = "tests_passed"
    TESTS_FAILED = "tests_failed"
    
    # ===== Deployment phase =====
    DEPLOYING = "deploying"
    DEPLOYED = "deployed"
    RELEASE_APPROVED = "release_approved"
    RELEASED = "released"
    
    # ===== Terminal states =====
    FAILED = "failed"
    CANCELLED = "cancelled"
