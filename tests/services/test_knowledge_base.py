from pathlib import Path

from services.knowledge_base import KnowledgeBase


def project():
    return {
        "project_id": "p1", "name": "Swarm Demo", "purpose": "Automate swarm delivery",
        "setup": "pip install -r requirements.txt", "test_command": "pytest -q",
        "phases": [
            {"name": "Planning", "description": "WBS and acceptance criteria", "acceptance_criteria": ["plan approved"], "files": ["docs/plan.md"]},
            {"name": "Delivery", "description": "Sentinel reports and merged patches", "sentinel_reports": ["sentinel: pass"], "merged_patches": ["services/foo.py"]},
        ],
    }


def test_readme_contains_name_phases_and_test_command():
    kb = KnowledgeBase(); kb.ingest_project(project())
    readme = kb.generate_readme("p1")
    assert "Swarm Demo" in readme
    assert "Planning" in readme and "Delivery" in readme
    assert "pytest -q" in readme


def test_adr_writes_yaml_frontmatter_and_decision(tmp_path: Path):
    kb = KnowledgeBase(tmp_path)
    kb.ingest_project(project())
    path = kb.generate_adr("p1", "Use SQLite", "Need durable local state", "Simple deployment")
    text = path.read_text(encoding="utf-8")
    assert text.startswith("---\n")
    assert "project_id: p1" in text
    assert "status: accepted" in text
    assert "decision: 'Use SQLite'" in text
    assert "# Decision\n\nUse SQLite" in text


def test_search_finds_hits_across_phases():
    kb = KnowledgeBase(); kb.ingest_project(project())
    hits = kb.search("sentinel patches")
    assert any(h.phase == "Delivery" for h in hits)
    assert hits[0].score > 0


def test_summary_aggregates_phases_files_and_decisions(tmp_path: Path):
    kb = KnowledgeBase(tmp_path); kb.ingest_project(project())
    kb.generate_adr("p1", "Use SQLite", "context", "consequence")
    summary = kb.summary("p1")
    assert summary["phase_count"] == 2
    assert summary["file_count"] == 2
    assert summary["decision_count"] == 1
    assert "docs/plan.md" in summary["files"]
    assert "services/foo.py" in summary["files"]
