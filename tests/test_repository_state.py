from pathlib import Path

from scripts.repository_state import (
    inspect_repository,
    load_contract,
    migration_heads,
    validate_contract,
)


ROOT = Path(__file__).resolve().parents[1]


def test_tracked_repository_state_matches_canonical_runtime() -> None:
    contract = load_contract(ROOT)
    report = inspect_repository(ROOT, "HEAD")

    assert report["classification"] == "VERIFIED"
    assert report["head_sha"]
    assert report["base_sha"]
    assert validate_contract(ROOT, contract, report) == []


def test_migration_graph_has_exact_declared_head() -> None:
    contract = load_contract(ROOT)

    assert migration_heads(ROOT) == [contract["canonical_alembic_head"]]


def test_agent_protocol_forbids_memory_as_repository_evidence() -> None:
    protocol = (ROOT / "AGENTS.md").read_text(encoding="utf-8")

    assert "Memory is historical context, never evidence" in protocol
    assert "git fetch origin --prune" in protocol
    assert "VERIFIED" in protocol
    assert "UNKNOWN" in protocol


def test_supported_agent_bootstraps_share_one_canonical_protocol() -> None:
    for relative_path in (
        "CLAUDE.md",
        "GEMINI.md",
        ".github/copilot-instructions.md",
    ):
        bootstrap = (ROOT / relative_path).read_text(encoding="utf-8")
        assert "AGENTS.md" in bootstrap
        assert "git fetch origin --prune" in bootstrap
        assert "scripts/repository_state.py" in bootstrap
