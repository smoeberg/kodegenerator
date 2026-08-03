# infrastructure/database/dor_runtime_db.py (Udvidet)
def _load_workflow_templates(self) -> None:
    """Indlæs foruddefinerede Workflow Templates."""
    # ... (Forrige kode for Feature Development, Bug Fix, etc.)

    from templates.deployment import deployment_template
    from templates.incident_response import incident_response_template

    self.workflow_template_registry.add_template(deployment_template)
    self.workflow_template_registry.add_template(incident_response_template)
