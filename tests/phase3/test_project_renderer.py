import pytest

from generation.project_renderer import ProjectRenderer
from generation.project_spec import ArchitectureKind, ProjectDefinition
from generation.scaffold_engine import ScaffoldEngine, ScaffoldFile, ScaffoldPlan


def project() -> ProjectDefinition:
    return ProjectDefinition(name="orders-api", architecture=ArchitectureKind.HEXAGONAL)


def plan() -> ScaffoldPlan:
    return ScaffoldEngine().generate(project())


def test_renderer_is_deterministic():
    renderer = ProjectRenderer()
    first = renderer.render(plan())
    second = renderer.render(plan())
    assert first.files == second.files
    assert first.manifest == second.manifest
    assert first.fingerprint == second.fingerprint


def test_renderer_canonicalizes_file_order():
    rendered = ProjectRenderer().render(plan())
    assert rendered.manifest == tuple(sorted(rendered.manifest))


def test_renderer_normalizes_line_endings():
    source = ScaffoldFile("src/domain/entities.py", "line1\r\nline2\rline3\n")
    custom = ScaffoldPlan(project=project(), files=(source,), architecture_contract=(source.path,))
    rendered = ProjectRenderer().render(custom)
    assert rendered.files[0].content == "line1\nline2\nline3\n"


def test_renderer_rejects_invalid_plan():
    source = ScaffoldFile("invalid/path.py", "pass\n")
    custom = ScaffoldPlan(project=project(), files=(source,), architecture_contract=("missing.py",))
    with pytest.raises(ValueError, match="invalid scaffold plan"):
        ProjectRenderer().render(custom)


def test_renderer_rejects_duplicate_paths():
    first = ScaffoldFile("src/domain/entities.py", "one\n")
    second = ScaffoldFile("src/domain/entities.py", "two\n")
    custom = ScaffoldPlan(project=project(), files=(first, second), architecture_contract=(first.path,))
    with pytest.raises(ValueError, match="duplicate rendered path"):
        ProjectRenderer().render(custom)


def test_renderer_does_not_change_scaffold_plan():
    original = plan()
    before = original.files
    ProjectRenderer().render(original)
    assert original.files == before
