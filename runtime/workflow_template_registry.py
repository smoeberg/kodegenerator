# runtime/workflow_template_registry.py
from typing import Dict, List, Optional
from domain.workflow_template import WorkflowTemplate

class WorkflowTemplateRegistry:
    """Central registrering af Workflow Templates."""

    def __init__(self):
        self.templates: Dict[str, WorkflowTemplate] = {}  # template_id → WorkflowTemplate

    def add_template(self, template: WorkflowTemplate) -> None:
        """Tilføj en Workflow Template til registret."""
        if template.id not in self.templates:
            self.templates[template.id] = template

    def get_template(self, template_id: str) -> Optional[WorkflowTemplate]:
        """Hent en Workflow Template ud fra ID."""
        return self.templates.get(template_id)

    def get_templates_by_capability(self, capability_id: str) -> List[WorkflowTemplate]:
        """Hent alle Workflow Templates, der kræver en given Capability."""
        return [
            template for template in self.templates.values()
            if capability_id in template.required_capabilities
        ]

    def get_all_templates(self) -> List[WorkflowTemplate]:
        """Hent alle Workflow Templates."""
        return list(self.templates.values())
