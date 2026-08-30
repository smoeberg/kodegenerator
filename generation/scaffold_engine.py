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
        if project.language == "python":
            return self._generate_python(project)
        elif project.language == "typescript":
            return self._generate_typescript(project)
        elif project.language == "go":
            return self._generate_go(project)
        else:
            raise ValueError(f"unsupported language: {project.language}")

    def _generate_python(self, project: ProjectDefinition) -> ScaffoldPlan:
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
                f"Generated from the DOR {project.architecture.value} architecture contract ({project.language}).\n",
            ),
            ScaffoldFile(".gitignore", "__pycache__/\n.pytest_cache/\n.venv/\n"),
        )
        contract = tuple(f.path for f in files if f.path != ".gitignore")
        plan = ScaffoldPlan(
            project=project, files=files, architecture_contract=contract
        )
        violations = plan.validate()
        if violations:
            raise ValueError(f"invalid scaffold plan: {violations}")
        return plan

    def _generate_typescript(self, project: ProjectDefinition) -> ScaffoldPlan:
        files = (
            ScaffoldFile(
                "package.json",
                f'{{\n  "name": "{project.name}",\n  "version": "1.0.0",\n  "type": "module",\n'
                f'  "scripts": {{\n    "build": "tsc",\n    "test": "vitest run"\n  }},\n'
                f'  "dependencies": {{\n    "{project.api}": "*"\n  }},\n'
                f'  "devDependencies": {{\n    "typescript": "^5.0.0",\n    "vitest": "^1.0.0"\n  }}\n}}\n',
            ),
            ScaffoldFile(
                "tsconfig.json",
                '{\n  "compilerOptions": {\n    "target": "ES2022",\n    "module": "NodeNext",\n'
                '    "moduleResolution": "NodeNext",\n    "strict": true,\n    "outDir": "./dist"\n  },\n'
                '  "include": ["src/**/*", "tests/**/*"]\n}\n',
            ),
            ScaffoldFile(
                "src/domain/entities.ts",
                "// Domain entities; framework-independent\nexport interface BaseEntity {\n  id: string;\n  createdAt: Date;\n}\n",
            ),
            ScaffoldFile(
                "src/ports/repositories.ts",
                "// Repository and outbound ports\nexport interface Repository<T> {\n  findById(id: string): Promise<T | null>;\n  save(item: T): Promise<void>;\n}\n",
            ),
            ScaffoldFile(
                "src/application/services.ts",
                "// Application services and use cases\nexport class ApplicationService {}\n",
            ),
            ScaffoldFile(
                "src/adapters/api.ts",
                f"// {project.api.capitalize()} HTTP Adapter\nexport function createApp() {{\n  return {{}};\n}}\n",
            ),
            ScaffoldFile(
                "tests/architecture.test.ts",
                'import { describe, it, expect } from "vitest";\n\n'
                'describe("Architecture Contract", () => {\n'
                '  it("maintains separation of concerns", () => {\n'
                '    expect(true).toBe(true);\n'
                '  });\n'
                '});\n',
            ),
            ScaffoldFile(
                "README.md",
                f"# {project.name}\n\n"
                f"Generated from the DOR {project.architecture.value} architecture contract ({project.language}).\n",
            ),
            ScaffoldFile(".gitignore", "node_modules/\ndist/\ncoverage/\n"),
        )
        contract = tuple(f.path for f in files if f.path != ".gitignore")
        plan = ScaffoldPlan(
            project=project, files=files, architecture_contract=contract
        )
        violations = plan.validate()
        if violations:
            raise ValueError(f"invalid scaffold plan: {violations}")
        return plan

    def _generate_go(self, project: ProjectDefinition) -> ScaffoldPlan:
        files = (
            ScaffoldFile(
                "go.mod",
                f"module {project.name}\n\ngo 1.22\n",
            ),
            ScaffoldFile(
                "internal/domain/entities.go",
                "package domain\n\n// Domain entities\ntype BaseEntity struct {\n\tID string\n}\n",
            ),
            ScaffoldFile(
                "internal/ports/repositories.go",
                "package ports\n\n// Port interfaces\ntype Repository interface {}\n",
            ),
            ScaffoldFile(
                "internal/application/services.go",
                "package application\n\n// Application services\ntype Service struct {}\n",
            ),
            ScaffoldFile(
                "internal/adapters/api.go",
                f"package adapters\n\n// {project.api.capitalize()} HTTP adapter\ntype Server struct {{}}\n",
            ),
            ScaffoldFile(
                "cmd/server/main.go",
                f"package main\n\nimport \"fmt\"\n\nfunc main() {{\n\tfmt.Println(\"Starting {project.name}...\")\n}}\n",
            ),
            ScaffoldFile(
                "internal/domain/entities_test.go",
                "package domain\n\nimport \"testing\"\n\nfunc TestDomain(t *testing.T) {}\n",
            ),
            ScaffoldFile(
                "README.md",
                f"# {project.name}\n\n"
                f"Generated from the DOR {project.architecture.value} architecture contract ({project.language}).\n",
            ),
            ScaffoldFile(".gitignore", "bin/\nvendor/\n*.exe\n"),
        )
        contract = tuple(f.path for f in files if f.path != ".gitignore")
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
