"""Pure deterministic rendering of validated scaffold plans.

The renderer materializes a validated ScaffoldPlan into an immutable project
representation. It deliberately performs no filesystem, Git, network, or LLM
operations; those concerns belong to later governed adapters.
"""

from dataclasses import dataclass
from hashlib import sha256
from pathlib import PurePosixPath

from generation.scaffold_engine import ScaffoldFile, ScaffoldPlan


@dataclass(frozen=True)
class RenderedFile:
    """One canonical generated project file."""

    path: str
    content: str


@dataclass(frozen=True)
class RenderedProject:
    """Immutable, deterministic project output ready for a later writer."""

    files: tuple[RenderedFile, ...]
    manifest: tuple[str, ...]
    fingerprint: str


class ProjectRenderer:
    """Render a validated scaffold plan without side effects."""

    def render(self, plan: ScaffoldPlan) -> RenderedProject:
        violations = plan.validate()
        if violations:
            raise ValueError(f"cannot render invalid scaffold plan: {violations}")

        files = tuple(
            RenderedFile(item.path, _normalize_content(item.content))
            for item in sorted(plan.files, key=lambda item: item.path)
        )
        _validate_files(files)

        manifest = tuple(item.path for item in files)
        payload = "\n".join(f"{item.path}\0{item.content}" for item in files)
        fingerprint = sha256(payload.encode("utf-8")).hexdigest()
        return RenderedProject(files=files, manifest=manifest, fingerprint=fingerprint)


def _normalize_content(content: str) -> str:
    """Canonicalize text so equivalent files render identically."""

    return content.replace("\r\n", "\n").replace("\r", "\n")


def _validate_files(files: tuple[RenderedFile, ...]) -> None:
    seen: set[str] = set()
    for item in files:
        path = PurePosixPath(item.path)
        if path.is_absolute() or ".." in path.parts or "" in path.parts:
            raise ValueError(f"unsafe rendered path: {item.path}")
        if item.path in seen:
            raise ValueError(f"duplicate rendered path: {item.path}")
        seen.add(item.path)
