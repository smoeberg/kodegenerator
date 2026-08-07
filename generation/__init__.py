"""Deterministic project architecture and scaffold generation."""

from generation.project_spec import ArchitectureKind, ProjectDefinition
from generation.scaffold_engine import ScaffoldEngine, ScaffoldPlan

__all__ = [
    "ArchitectureKind",
    "ProjectDefinition",
    "ScaffoldEngine",
    "ScaffoldPlan",
]
