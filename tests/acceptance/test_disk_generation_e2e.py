"""End-to-End Acceptance test verifying that generated projects are materialized to disk."""

from __future__ import annotations

import tempfile
from pathlib import Path

from generation.project_renderer import ProjectRenderer
from generation.project_spec import ArchitectureKind, ProjectDefinition
from generation.scaffold_engine import ScaffoldEngine


def test_materialize_scaffold_to_disk():
    """Verify that a project definition is scaffolded, rendered and materialized to disk."""
    project = ProjectDefinition(
        name="billing-service",
        architecture=ArchitectureKind.HEXAGONAL,
        language="python",
        api="fastapi",
        database="postgresql",
    )
    engine = ScaffoldEngine()
    plan = engine.generate(project)
    assert not plan.validate()

    renderer = ProjectRenderer()
    rendered = renderer.render(plan)

    with tempfile.TemporaryDirectory(prefix="dor-disk-test-") as temp_dir:
        target_dir = Path(temp_dir) / "billing-service"
        written_files = renderer.write_to_disk(rendered, target_dir)

        assert target_dir.exists()
        assert len(written_files) == len(rendered.files)

        # Verify key project files exist and have non-empty content
        for item in rendered.files:
            file_path = target_dir / item.path
            assert file_path.exists(), f"Expected file {item.path} on disk"
            assert file_path.is_file()
            assert file_path.read_text(encoding="utf-8") == item.content

        # Verify manifest matches
        assert set(written_files.keys()) == set(rendered.manifest)


def test_materialize_rejects_unsafe_paths():
    """Verify that path traversal attempts fail closed."""
    from generation.project_renderer import RenderedFile, RenderedProject

    rendered = RenderedProject(
        files=(RenderedFile("../evil.py", "malicious"),),
        manifest=("../evil.py",),
        fingerprint="dummy",
    )
    renderer = ProjectRenderer()
    with tempfile.TemporaryDirectory() as temp_dir:
        import pytest
        with pytest.raises(ValueError, match="unsafe"):
            renderer.write_to_disk(rendered, Path(temp_dir))
