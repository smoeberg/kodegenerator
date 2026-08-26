"""
Prompt Engine Service

Automatisk generering af capability-taggede prompts for WBS-opgaver.

Formål: Når WBS-orchestratoren nedbryder et projekt, skal hver opgave 
medføre en færdig, deterministisk instruktion med kontekst, restriktioner 
og acceptkriterier, så enhver worker-bot kan udføre den uden yderligere 
menneskelig vejledning.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum, auto
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, TYPE_CHECKING
import uuid

from domain.architecture_contract_v1 import (
    ArchitectureContractV1,
    DependencyRuleV1,
    LayerV1,
    QualityGateV1,
)
from domain.task import Task, TaskStatus, TaskPriority
from services.wbs_orchestrator import TaskPhase

if TYPE_CHECKING:
    from domain.ast_policy import ASTPolicy


class PromptPhase(str, Enum):
    """Faser for prompt templates."""
    DOMAIN_MODELS = "DOMAIN_MODELS"
    SERVICE_LAYER = "SERVICE_LAYER"
    API = "API"
    TESTS = "TESTS"
    DOCS = "DOCS"
    SECURITY = "SECURITY"


@dataclass(frozen=True)
class WBSContext:
    """Kontekst for WBS-opgave prompt generering."""
    task: Task
    contract: ArchitectureContractV1
    repo_context: Dict[str, Any]
    ast_policy: Optional["ASTPolicy"] = None
    
    @property
    def task_phase(self) -> TaskPhase:
        """Hent task phase fra metadata."""
        phase_str = self.task.metadata.get("phase", "DOMAIN_MODELS")
        
        # Map string to TaskPhase enum
        phase_map = {
            "DOMAIN_MODELS": TaskPhase.DOMAIN_MODELS,
            "SERVICE_LAYER": TaskPhase.SERVICE_LAYER,
            "API_ENDPOINTS": TaskPhase.API_ENDPOINTS,
            "TEST_SUITES": TaskPhase.TEST_SUITES,
            "VERIFICATION": TaskPhase.VERIFICATION,
            "DOCUMENTATION": TaskPhase.DOCUMENTATION,
        }
        
        return phase_map.get(phase_str, TaskPhase.DOMAIN_MODELS)
    
    @property
    def layer_name(self) -> str:
        """Hent layer navn fra task metadata."""
        return self.task.metadata.get("layer", "domain")


@dataclass(frozen=True)
class PromptTemplate:
    """Skabelon for prompt generering."""
    phase: PromptPhase
    template_path: str
    required_capabilities: List[str]
    default_values: Dict[str, Any] = field(default_factory=dict)


# Standard prompt templates
PROMPT_TEMPLATES: Dict[PromptPhase, PromptTemplate] = {
    PromptPhase.DOMAIN_MODELS: PromptTemplate(
        phase=PromptPhase.DOMAIN_MODELS,
        template_path="templates/prompts/DOMAIN_MODELS.md",
        required_capabilities=[
            "cap.domain.modeling",
            "cap.ast.write",
            "cap.implementation",
        ],
    ),
    PromptPhase.SERVICE_LAYER: PromptTemplate(
        phase=PromptPhase.SERVICE_LAYER,
        template_path="templates/prompts/SERVICE_LAYER.md",
        required_capabilities=[
            "cap.code.generation",
            "cap.implementation",
            "cap.ast.write",
        ],
    ),
    PromptPhase.API: PromptTemplate(
        phase=PromptPhase.API,
        template_path="templates/prompts/API.md",
        required_capabilities=[
            "cap.code.generation",
            "cap.implementation",
            "cap.ast.write",
        ],
    ),
    PromptPhase.TESTS: PromptTemplate(
        phase=PromptPhase.TESTS,
        template_path="templates/prompts/TESTS.md",
        required_capabilities=[
            "cap.run.tests",
            "cap.verification",
            "cap.implementation",
        ],
    ),
    PromptPhase.DOCS: PromptTemplate(
        phase=PromptPhase.DOCS,
        template_path="templates/prompts/DOCS.md",
        required_capabilities=[
            "cap.documentation",
        ],
    ),
    PromptPhase.SECURITY: PromptTemplate(
        phase=PromptPhase.SECURITY,
        template_path="templates/prompts/SECURITY.md",
        required_capabilities=[
            "cap.security.audit",
            "cap.implementation",
        ],
    ),
}


@dataclass(frozen=True)
class PromptGenerationResult:
    """Resultat af prompt generering."""
    prompt: str
    prompt_id: str
    phase: PromptPhase
    task_id: str
    contract_id: str
    fingerprint: str
    generated_at: datetime
    
    def to_dict(self) -> Dict[str, Any]:
        """Konverter til dictionary."""
        return {
            "prompt": self.prompt,
            "prompt_id": self.prompt_id,
            "phase": self.phase.value,
            "task_id": self.task_id,
            "contract_id": self.contract_id,
            "fingerprint": self.fingerprint,
            "generated_at": self.generated_at.isoformat(),
        }


class PromptEngineError(Exception):
    """Base exception for prompt engine errors."""
    pass


class PromptEngine:
    """
    Motor der automatisk genererer capability-taggede prompts for WBS-opgaver.
    
    Hovedfunktioner:
    - build_task_prompt: Generer komplet prompt for en WBS-opgave
    - Deterministisk output: Samme input producerer altid samme prompt
    - Template-baseret: Understøtter forskellige faser (DOMAIN, SERVICE, API, etc.)
    """
    
    def __init__(
        self,
        *,
        repository_root: Path | str = ".",
        templates_dir: Path | str = "templates/prompts",
    ):
        """
        Initialiser prompt engine.
        
        Args:
            repository_root: Rodsti til repository
            templates_dir: Mappe med prompt templates
        """
        self.repository_root = Path(repository_root).resolve()
        self.templates_dir = Path(templates_dir).resolve()
        
        # Validér at templates directory eksisterer
        if not self.templates_dir.exists():
            raise PromptEngineError(
                f"Templates directory not found: {self.templates_dir}"
            )
    
    def _load_template(self, template_path: str) -> str:
        """Indlæs template fil."""
        # Extract just the filename from the template path
        template_filename = Path(template_path).name
        full_path = self.templates_dir / template_filename
        
        if not full_path.exists():
            raise PromptEngineError(f"Template not found: {full_path}")
        
        return full_path.read_text(encoding="utf-8")
    
    def _get_phase_from_task(self, task: Task) -> PromptPhase:
        """Hent fase fra task metadata."""
        phase_str = task.metadata.get("phase", "DOMAIN_MODELS")
        
        try:
            return PromptPhase(phase_str)
        except ValueError:
            # Fallback til DOMAIN_MODELS
            return PromptPhase.DOMAIN_MODELS
    
    def _get_layer_info(
        self,
        contract: ArchitectureContractV1,
        layer_id: Optional[str] = None,
    ) -> Optional[LayerV1]:
        """Hent layer information fra kontrakt."""
        if layer_id:
            for layer in contract.layers:
                if layer.id == layer_id:
                    return layer
        
        # Return first layer as default
        if contract.layers:
            return contract.layers[0]
        
        return None
    
    def _compute_fingerprint(self, data: str) -> str:
        """Beregn SHA-256 fingerprint af data."""
        return hashlib.sha256(data.encode("utf-8")).hexdigest()
    
    def _format_dependency_rules(
        self,
        contract: ArchitectureContractV1,
    ) -> str:
        """Formater dependency rules til prompt."""
        if not contract.dependency_rules:
            return "- No dependency rules defined"
        
        lines = []
        for rule in contract.dependency_rules:
            lines.append(f"- **{rule.id}**: {rule.source} may depend on: {', '.join(rule.may_depend_on)}")
            if rule.severity:
                lines.append(f"  - Severity: {rule.severity}")
        
        return "\n".join(lines)
    
    def _format_quality_gates(
        self,
        contract: ArchitectureContractV1,
    ) -> str:
        """Formater quality gates til prompt."""
        if not contract.quality_gates:
            return "- No quality gates defined"
        
        lines = []
        for gate in contract.quality_gates:
            required = "REQUIRED" if gate.required else "OPTIONAL"
            lines.append(f"- **{gate.id}** ({gate.type}): {required}")
        
        return "\n".join(lines)
    
    def _format_forbidden_imports(
        self,
        ast_policy: Optional["ASTPolicy"],
    ) -> str:
        """Formater forbudte imports til prompt."""
        if ast_policy is None:
            return "- No forbidden imports"
        
        # Check if ast_policy has forbidden_imports attribute
        if hasattr(ast_policy, 'forbidden_imports') and ast_policy.forbidden_imports:
            lines = []
            for imp in ast_policy.forbidden_imports:
                lines.append(f"- `from {imp} import ...` or `import {imp}`")
            return "\n".join(lines) if lines else "- No forbidden imports"
        
        return "- No forbidden imports"
    
    def _format_forbidden_calls(
        self,
        ast_policy: Optional["ASTPolicy"],
    ) -> str:
        """Formater forbudte function calls til prompt."""
        if ast_policy is None:
            return "- No forbidden function calls"
        
        # Check if ast_policy has forbidden_calls attribute
        if hasattr(ast_policy, 'forbidden_calls') and ast_policy.forbidden_calls:
            lines = []
            for call in ast_policy.forbidden_calls:
                lines.append(f"- `{call}`")
            return "\n".join(lines) if lines else "- No forbidden function calls"
        
        return "- No forbidden function calls"
    
    def _format_security_constraints(
        self,
        ast_policy: Optional["ASTPolicy"],
    ) -> str:
        """Formater sikkerhedsregler til prompt."""
        if ast_policy is None:
            return "- No additional security constraints"
        
        constraints = []
        
        # Check various security-related attributes
        if hasattr(ast_policy, 'no_path_traversal') and ast_policy.no_path_traversal:
            constraints.append("- No path traversal writes allowed")
        
        if hasattr(ast_policy, 'no_exec') and ast_policy.no_exec:
            constraints.append("- No exec/eval functions allowed")
        
        if hasattr(ast_policy, 'no_shell') and ast_policy.no_shell:
            constraints.append("- No shell command execution allowed")
        
        if hasattr(ast_policy, 'no_network') and ast_policy.no_network:
            constraints.append("- No network calls allowed")
        
        return "\n".join(constraints) if constraints else "- No additional security constraints"
    
    def _get_output_files(
        self,
        task: Task,
        layer: Optional[LayerV1],
    ) -> Tuple[str, List[str]]:
        """Hent output filer baseret på task og layer."""
        task_name = task.name.lower().replace(" ", "_")
        layer_path = layer.path if layer else "src/domain"
        
        # Map phase to file types
        phase = self._get_phase_from_task(task)
        
        file_mappings = {
            PromptPhase.DOMAIN_MODELS: [
                f"{layer_path}/{task_name}.py",
                f"tests/test_{task_name}.py",
            ],
            PromptPhase.SERVICE_LAYER: [
                f"{layer_path}/{task_name}_service.py",
                f"{layer_path}/dtos.py",
                f"tests/test_{task_name}_service.py",
            ],
            PromptPhase.API: [
                f"{layer_path}/{task_name}_router.py",
                f"{layer_path}/schemas.py",
                f"tests/test_{task_name}_api.py",
            ],
            PromptPhase.TESTS: [
                f"tests/test_{task_name}.py",
            ],
            PromptPhase.DOCS: [
                f"docs/{task_name}.md",
            ],
            PromptPhase.SECURITY: [
                f"{layer_path}/security.py",
                f"tests/test_security.py",
            ],
        }
        
        files = file_mappings.get(phase, [f"{layer_path}/{task_name}.py"])
        
        # Format as string
        output_files_str = "\n".join([f"- `{f}`" for f in files])
        output_files_json = json.dumps(files)
        
        return output_files_str, files
    
    def _get_test_files(
        self,
        output_files: List[str],
    ) -> str:
        """Hent test filer fra output files."""
        test_files = [f for f in output_files if "test" in f.lower()]
        return json.dumps(test_files) if test_files else "[]"
    
    def _get_acceptance_criteria(self, task: Task) -> str:
        """Hent acceptance criteria fra task."""
        criteria = task.metadata.get("acceptance_criteria", [])
        
        if isinstance(criteria, list):
            if not criteria:
                return "- No specific acceptance criteria defined"
            return "\n".join([f"- {c}" for c in criteria])
        
        if isinstance(criteria, str):
            return criteria
        
        return "- No specific acceptance criteria defined"
    
    def _get_allowed_dependencies(
        self,
        contract: ArchitectureContractV1,
        layer: Optional[LayerV1],
    ) -> str:
        """Hent tilladte dependencies for layer."""
        if layer is None:
            return "domain, application, ports"
        
        # Find dependency rules for this layer
        allowed = set()
        for rule in contract.dependency_rules:
            if rule.source == layer.id:
                allowed.update(rule.may_depend_on)
        
        if not allowed:
            return "domain, application, ports"
        
        return ", ".join(allowed)
    
    def _get_dependency_rules_summary(
        self,
        contract: ArchitectureContractV1,
        layer: Optional[LayerV1],
    ) -> str:
        """Hent samlet oversigt over dependency rules."""
        if layer is None:
            return "Follow contract dependency rules"
        
        rules = []
        for rule in contract.dependency_rules:
            if rule.source == layer.id:
                rules.append(f"{rule.source} -> {', '.join(rule.may_depend_on)}")
        
        if not rules:
            return "No specific dependency rules for this layer"
        
        return "; ".join(rules)
    
    def _format_layer_dependencies(
        self,
        contract: ArchitectureContractV1,
        layer: Optional[LayerV1],
    ) -> str:
        """Formater layer dependencies."""
        if layer is None:
            return "- No layer dependencies"
        
        # This would normally come from the architecture graph
        # For now, return a simple representation
        return "- No dependency information available"
    
    def _get_task_name(self, task: Task) -> str:
        """Hent task navn."""
        return task.name
    
    def _get_task_description(self, task: Task) -> str:
        """Hent task beskrivelse."""
        return task.description or "No description provided"
    
    def build_task_prompt(
        self,
        wbs_context: WBSContext,
    ) -> PromptGenerationResult:
        """
        Byg en komplet prompt for en WBS-opgave.
        
        Args:
            wbs_context: Kontekst indeholdende task, kontrakt, repo kontekst og AST policy
            
        Returns:
            PromptGenerationResult med den genererede prompt og metadata
        """
        task = wbs_context.task
        contract = wbs_context.contract
        repo_context = wbs_context.repo_context
        ast_policy = wbs_context.ast_policy
        
        # Bestem fase
        phase = self._get_phase_from_task(task)
        
        # Hent layer information
        layer_id = task.metadata.get("layer_id") or task.metadata.get("layer", "domain")
        layer = self._get_layer_info(contract, layer_id)
        
        # Indlæs template
        template = self._load_template(PROMPT_TEMPLATES[phase].template_path)
        
        # Opret substitution dictionary
        substitutions = {
            # Grundlæggende information
            "task_id": task.id,
            "task_name": self._get_task_name(task),
            "task_description": self._get_task_description(task),
            
            # Kontrakt information
            "contract_id": contract.contract_id,
            "contract_version": contract.version,
            "project_name": contract.project_name,
            "architecture_style": contract.style,
            "language": contract.language or "python",
            "framework": repo_context.get("framework", "FastAPI"),
            
            # Layer information
            "layer_name": layer.id if layer else "domain",
            "layer_path": layer.path if layer else "src/domain",
            "layer_dependencies": self._format_layer_dependencies(contract, layer),
            
            # Dependency rules
            "dependency_rules": self._format_dependency_rules(contract),
            "dependency_rules_summary": self._get_dependency_rules_summary(contract, layer),
            
            # AST Policy
            "forbidden_imports": self._format_forbidden_imports(ast_policy),
            "forbidden_calls": self._format_forbidden_calls(ast_policy),
            "security_constraints": self._format_security_constraints(ast_policy),
            
            # Acceptance criteria
            "acceptance_criteria": self._get_acceptance_criteria(task),
            
            # Output requirements
            "output_files_str": self._get_output_files(task, layer)[0],
            "output_files_json": json.dumps([f for f in self._get_output_files(task, layer)[1]]),
            "test_files": self._get_test_files(self._get_output_files(task, layer)[1]),
            
            # Project root
            "project_root": str(self.repository_root),
            
            # API-specific
            "api_base_path": repo_context.get("api_base_path", "/api/v1"),
            "api_version": repo_context.get("api_version", "v1"),
            "api_standard": repo_context.get("api_standard", "REST"),
            "authentication": repo_context.get("authentication", "Bearer JWT"),
            
            # Quality gates
            "quality_gates": self._format_quality_gates(contract),
            
            # Coverage requirement
            "coverage_requirement": repo_context.get("coverage_requirement", 80),
            
            # Target layer for tests
            "target_layer": task.metadata.get("target_layer", "domain"),
            
            # Allowed dependencies
            "allowed_dependencies": self._get_allowed_dependencies(contract, layer),
            
            # Component info for docs
            "component_name": task.metadata.get("component", task.name),
            "audience": repo_context.get("audience", "Developers"),
            "documentation_purpose": repo_context.get("purpose", "API Documentation"),
            
            # Security scope
            "security_scope": task.metadata.get("security_scope", "Authentication & Authorization"),
            "authentication_requirements": repo_context.get("auth_requirements", "JWT-based"),
            "authorization_requirements": repo_context.get("authz_requirements", "Role-based (RBAC)"),
            "data_protection_requirements": repo_context.get("data_protection", "Encryption at rest and in transit"),
            "audit_requirements": repo_context.get("audit", "All security events logged"),
        }
        
        # Udfør substitution
        prompt = template
        for key, value in substitutions.items():
            # Replace both {{key}} and {key} patterns
            prompt = prompt.replace("{" + key + "}", str(value))
        
        # Also handle double braces for compatibility
        for key, value in substitutions.items():
            prompt = prompt.replace("{{" + key + "}}", str(value))
        
        # Generér fingerprint
        prompt_fingerprint = self._compute_fingerprint(prompt)
        
        # Opret resultat
        result = PromptGenerationResult(
            prompt=prompt,
            prompt_id=str(uuid.uuid5(uuid.NAMESPACE_DNS, f"{task.id}-{contract.contract_id}")),
            phase=phase,
            task_id=task.id,
            contract_id=contract.contract_id,
            fingerprint=prompt_fingerprint,
            generated_at=datetime.now(timezone.utc),
        )
        
        return result
    
    def build_task_prompt_deterministic(
        self,
        task: Task,
        contract: ArchitectureContractV1,
        repo_context: Dict[str, Any],
        ast_policy: Optional["ASTPolicy"] = None,
    ) -> PromptGenerationResult:
        """
        Deterministisk version af build_task_prompt.
        
        Samme input producerer ALTID samme prompt.
        
        Args:
            task: WBS task
            contract: Arkitektur kontrakt
            repo_context: Repository kontekst
            ast_policy: AST policy
            
        Returns:
            PromptGenerationResult med deterministisk prompt
        """
        # Opret kontekst
        context = WBSContext(
            task=task,
            contract=contract,
            repo_context=repo_context,
            ast_policy=ast_policy,
        )
        
        return self.build_task_prompt(context)
    
    def get_template_phase(
        self,
        task: Task,
    ) -> PromptPhase:
        """Hent template fase for en task."""
        return self._get_phase_from_task(task)
    
    def list_available_templates(self) -> List[str]:
        """List tilgængelige prompt templates."""
        templates = []
        for phase in PromptPhase:
            template_path = PROMPT_TEMPLATES[phase].template_path
            # Extract just the filename from the template path
            template_filename = Path(template_path).name
            if (self.templates_dir / template_filename).exists():
                templates.append(phase.value)
        return templates
    
    def validate_prompt(
        self,
        result: PromptGenerationResult,
    ) -> Tuple[bool, List[str]]:
        """
        Valider en genereret prompt.
        
        Args:
            result: PromptGenerationResult at validere
            
        Returns:
            Tuple of (is_valid, list of errors)
        """
        errors = []

        # Check required sections
        required_sections = [
            "ROLE & CAPABILITIES",
            "ARCHITECTURE CONTEXT",
            "AST POLICY & SECURITY RULES",
            "ACCEPTANCE CRITERIA",
            "OUTPUT REQUIREMENTS",
            "TASK INSTRUCTION",
        ]
        for section in required_sections:
            if section not in result.prompt:
                errors.append(f"Missing required section: {section}")
        
        # Check for unreplaced placeholders
        if "{" in result.prompt and "}" in result.prompt:
            errors.append("Unreplaced placeholders found in prompt")
        
        # Check fingerprint
        computed_fingerprint = self._compute_fingerprint(result.prompt)
        if computed_fingerprint != result.fingerprint:
            errors.append("Fingerprint mismatch - prompt may have been modified")
        
        return len(errors) == 0, errors
