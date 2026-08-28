"""Deterministic scaffold planning and architecture validation."""

from dataclasses import dataclass
from hashlib import sha256
from pathlib import PurePosixPath

from generation.project_spec import ArchitectureKind, ProjectDefinition


@dataclass(frozen=True)
class ScaffoldFile:
    path: str
    content: str


@dataclass(frozen=True)
class ScaffoldPlan:
    project: ProjectDefinition
    files: tuple[ScaffoldFile, ...]
    architecture_contract: tuple[str, ...]

    @property
    def fingerprint(self) -> str:
        payload = "\n".join(f"{item.path}\0{item.content}" for item in self.files)
        return sha256(payload.encode("utf-8")).hexdigest()

    def validate(self) -> tuple[str, ...]:
        actual = {item.path for item in self.files}
        missing = sorted(set(self.architecture_contract) - actual)
        invalid = sorted(path for path in actual if not _safe_relative_path(path))
        return tuple(
            [
                *(f"missing:{path}" for path in missing),
                *(f"unsafe:{path}" for path in invalid),
            ]
        )


class ScaffoldEngine:
    """Create a deterministic project plan; never writes to disk itself."""

    def generate(self, project: ProjectDefinition) -> ScaffoldPlan:
        if project.architecture is not ArchitectureKind.HEXAGONAL:
            raise ValueError(f"unsupported architecture: {project.architecture}")

        package = project.name.replace("-", "_")
        files = (
            ScaffoldFile("src/domain/__init__.py", ""),
            ScaffoldFile("src/application/__init__.py", ""),
            ScaffoldFile("src/ports/__init__.py", ""),
            ScaffoldFile("src/adapters/__init__.py", ""),
            ScaffoldFile(
                "src/domain/entities.py",
                '"""Domain entities; framework-independent by contract."""\n',
            ),
            ScaffoldFile(
                "src/application/services.py",
                '"""Application use cases; depend on ports, not adapters."""\n',
            ),
            ScaffoldFile(
                "src/ports/repositories.py",
                '"""Ports owned by the application/domain boundary."""\n',
            ),
            ScaffoldFile(
                "src/adapters/api.py",
                '"""FastAPI adapter; transport concerns stay outside the domain."""\n',
            ),
            ScaffoldFile("tests/__init__.py", ""),
            ScaffoldFile(
                "tests/test_architecture.py",
                "def test_hexagonal_packages_import():\n"
                "    import src.adapters\n"
                "    import src.application\n"
                "    import src.domain\n"
                "    import src.ports\n\n"
                "    assert {src.adapters.__package__, src.application.__package__, "
                "src.domain.__package__, src.ports.__package__} == "
                "{'src.adapters', 'src.application', 'src.domain', 'src.ports'}\n",
            ),
            ScaffoldFile(
                "pyproject.toml",
                f"[project]\nname = \"{package}\"\nrequires-python = \">=3.11\"\n\n",
            ),
            ScaffoldFile(
                "README.md",
                f"# {project.name}\n\n"
                "Generated from the DOR P3-15 hexagonal architecture contract.\n",
            ),
            ScaffoldFile(".gitignore", "__pycache__/\n.pytest_cache/\n.venv/\n"),
        )
        contract = (
            "src/domain/__init__.py",
            "src/application/__init__.py",
            "src/ports/__init__.py",
            "src/adapters/__init__.py",
            "src/domain/entities.py",
            "src/application/services.py",
            "src/ports/repositories.py",
            "src/adapters/api.py",
            "tests/test_architecture.py",
            "pyproject.toml",
            "README.md",
            ".gitignore",
        )
        plan = ScaffoldPlan(
            project=project, files=files, architecture_contract=contract
        )
        violations = plan.validate()
        if violations:
            raise ValueError(f"invalid scaffold plan: {violations}")
        return plan


def _safe_relative_path(path: str) -> bool:
    parsed = PurePosixPath(path)
    return (
        not parsed.is_absolute()
        and ".." not in parsed.parts
        and "" not in parsed.parts
    )
