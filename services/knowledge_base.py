"""Structured project knowledge ingestion, search, summaries and auto-docs."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping
import re


@dataclass(frozen=True)
class KnowledgeHit:
    project_id: str
    phase: str
    kind: str
    text: str
    score: float
    metadata: Mapping[str, Any] = field(default_factory=dict)


class KnowledgeBase:
    def __init__(self, docs_root: str | Path = ".") -> None:
        self.docs_root = Path(docs_root)
        self._projects: dict[str, dict[str, Any]] = {}
        self._entries: list[KnowledgeHit] = []
        self._decisions: dict[str, list[dict[str, str]]] = {}

    def ingest_project(self, project: Mapping[str, Any] | Any) -> None:
        data = _as_dict(project)
        project_id = str(data.get("project_id", data.get("id", data.get("name", "project"))))
        self._projects[project_id] = data
        self._entries = [e for e in self._entries if e.project_id != project_id]
        phases = data.get("phases", data.get("wbs", [])) or []
        for index, phase in enumerate(phases, 1):
            p = _as_dict(phase)
            phase_name = str(p.get("name", p.get("id", f"Phase {index}")))
            parts: list[tuple[str, str]] = []
            for key in ("wbs", "plan", "description", "acceptance_criteria", "sentinel_reports", "patches", "merged_patches", "files", "open_points"):
                value = p.get(key)
                if value is not None:
                    parts.append((key, _stringify(value)))
            if not parts:
                parts.append(("phase", _stringify(p)))
            for kind, text in parts:
                self._entries.append(KnowledgeHit(project_id, phase_name, kind, text, 0.0, {"phase_index": index}))

    def generate_readme(self, project_id: str) -> str:
        project = self._projects[project_id]
        name = str(project.get("name", project_id))
        purpose = project.get("purpose", project.get("description", "Project documentation generated from the knowledge base."))
        phases = project.get("phases", project.get("wbs", [])) or []
        lines = [f"# {name}", "", "## Purpose", "", _stringify(purpose), "", "## Architecture overview", ""]
        for i, phase in enumerate(phases, 1):
            p = _as_dict(phase)
            lines.append(f"{i}. **{p.get('name', p.get('id', f'Phase {i}'))}** — {p.get('description', 'See indexed WBS and reports.')}" )
        lines += ["", "## Setup", "", _stringify(project.get("setup", "Install the project dependencies and configure the required environment variables.")), "", "## Tests", "", "```bash", str(project.get("test_command", "pytest")), "```", ""]
        return "\n".join(lines)

    def generate_adr(self, project_id: str, decision: str, context: str, consequence: str) -> Path:
        directory = self.docs_root / "docs" / "adr"
        directory.mkdir(parents=True, exist_ok=True)
        slug = re.sub(r"[^a-z0-9]+", "-", decision.lower()).strip("-") or "decision"
        existing = sorted(directory.glob("*.md"))
        number = len(existing) + 1
        path = directory / f"{number:04d}-{slug}.md"
        text = f"---\nproject_id: {project_id}\nstatus: accepted\ndecision: {_yaml(decision)}\n---\n\n# Decision\n\n{decision}\n\n## Context\n\n{context}\n\n## Consequence\n\n{consequence}\n"
        path.write_text(text, encoding="utf-8")
        self._decisions.setdefault(project_id, []).append({"path": str(path), "decision": decision, "context": context, "consequence": consequence})
        return path

    def search(self, query: str) -> list[KnowledgeHit]:
        terms = [t.lower() for t in re.findall(r"\w+", query) if t.strip()]
        results: list[KnowledgeHit] = []
        for entry in self._entries:
            haystack = f"{entry.phase} {entry.kind} {entry.text}".lower()
            score = sum(haystack.count(term) for term in terms)
            if score:
                results.append(KnowledgeHit(entry.project_id, entry.phase, entry.kind, entry.text, float(score), entry.metadata))
        return sorted(results, key=lambda h: (-h.score, h.phase, h.kind))

    def summary(self, project_id: str) -> dict[str, Any]:
        entries = [e for e in self._entries if e.project_id == project_id]
        project = self._projects[project_id]
        phases = sorted({e.phase for e in entries})
        files: set[str] = set()
        for e in entries:
            if e.kind in {"files", "patches", "merged_patches"}:
                files.update(re.findall(r"[\w./-]+\.[A-Za-z0-9]+", e.text))
        return {"project_id": project_id, "phases": phases, "phase_count": len(phases), "files": sorted(files), "file_count": len(files), "decisions": list(self._decisions.get(project_id, [])), "decision_count": len(self._decisions.get(project_id, [])), "open_points": _collect_open_points(project)}


def _as_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, Mapping): return dict(value)
    if hasattr(value, "model_dump"): return dict(value.model_dump())
    if hasattr(value, "__dict__"): return dict(vars(value))
    raise TypeError("project/phase must be a mapping or object with model_dump/__dict__")


def _stringify(value: Any) -> str:
    if isinstance(value, str): return value
    if isinstance(value, (list, tuple, set)): return "\n".join(f"- {_stringify(v)}" for v in value)
    if isinstance(value, Mapping): return "\n".join(f"{k}: {_stringify(v)}" for k, v in value.items())
    return str(value)


def _yaml(value: str) -> str:
    escaped = value.replace("'", "''")
    return f"'{escaped}'"


def _collect_open_points(project: Mapping[str, Any]) -> list[Any]:
    points = list(project.get("open_points", []) or [])
    for phase in project.get("phases", project.get("wbs", [])) or []:
        points.extend(_as_dict(phase).get("open_points", []) or [])
    return points
