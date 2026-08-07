import pytest
from pydantic import ValidationError

from generation.project_spec import ArchitectureKind, ProjectDefinition
from generation.scaffold_engine import ScaffoldEngine


def project() -> ProjectDefinition:
    return ProjectDefinition(name="orders-api", architecture=ArchitectureKind.HEXAGONAL)


def test_project_definition_is_strict():
    with pytest.raises(ValidationError):
        ProjectDefinition(
            name="orders-api",
            architecture=ArchitectureKind.HEXAGONAL,
            unexpected="value",
        )


def test_project_definition_rejects_unsupported_stack():
    with pytest.raises(ValidationError):
        ProjectDefinition(
            name="orders-api",
            architecture=ArchitectureKind.HEXAGONAL,
            language="typescript",
        )


def test_scaffold_contains_architecture_contract():
    plan = ScaffoldEngine().generate(project())
    assert plan.validate() == ()
    paths = {item.path for item in plan.files}
    assert "src/domain/entities.py" in paths
    assert "src/application/services.py" in paths
    assert "src/ports/repositories.py" in paths
    assert "src/adapters/api.py" in paths


def test_scaffold_is_deterministic():
    engine = ScaffoldEngine()
    first = engine.generate(project())
    second = engine.generate(project())
    assert first.files == second.files
    assert first.fingerprint == second.fingerprint


def test_scaffold_has_no_path_traversal():
    plan = ScaffoldEngine().generate(project())
    assert all(".." not in item.path.split("/") for item in plan.files)


def test_project_name_is_safe():
    with pytest.raises(ValidationError):
        ProjectDefinition(name="../orders", architecture=ArchitectureKind.HEXAGONAL)
