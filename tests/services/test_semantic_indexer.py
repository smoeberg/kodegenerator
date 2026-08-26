"""Tests for semantic code search and vector store."""
from __future__ import annotations

from pathlib import Path

import pytest

from services.semantic_indexer import SemanticIndexer, chunk_python_source, hash_embed
from services.vector_store import InMemoryVectorStore, SQLiteVectorStore, cosine_similarity

SAMPLE = '''\
"""Approval workflow helpers."""

def approve_request(request_id: str, actor: str) -> bool:
    """Approve a pending request after policy checks."""
    if not request_id:
        return False
    return _policy_allows(actor, request_id)

def _policy_allows(actor: str, request_id: str) -> bool:
    """Internal RBAC gate for approvals."""
    return actor.startswith("lead-")

class ApprovalService:
    """Service coordinating multi-step approvals."""

    def submit(self, payload: dict) -> str:
        return "ok"
'''


def test_chunk_python_extracts_functions_and_classes():
    chunks = chunk_python_source("app/approvals.py", SAMPLE)
    symbols = {c.symbol for c in chunks}
    assert "approve_request" in symbols
    assert "ApprovalService" in symbols
    assert any(c.kind == "docstring" for c in chunks)


def test_vector_store_cosine_and_sqlite_roundtrip(tmp_path: Path):
    a = hash_embed("approval policy rbac gate")
    b = hash_embed("approval policy rbac gate")
    c = hash_embed("unrelated networking socket timeout")
    assert cosine_similarity(a, b) == pytest.approx(1.0)
    assert cosine_similarity(a, c) < cosine_similarity(a, b)

    mem = InMemoryVectorStore()
    mem.upsert("1", a, {"path": "a.py"})
    mem.upsert("2", c, {"path": "c.py"})
    hits = mem.search(a, top_k=1)
    assert hits[0].record_id == "1"

    db = SQLiteVectorStore(tmp_path / "vec.db")
    db.upsert("1", a, {"path": "a.py"})
    db.upsert("2", c, {"path": "c.py"})
    hits2 = db.search(a, top_k=2)
    assert hits2[0].record_id == "1"
    assert db.count() == 2
    db.close()


def test_semantic_search_finds_approval_logic(tmp_path: Path):
    src = tmp_path / "approvals.py"
    src.write_text(SAMPLE, encoding="utf-8")
    indexer = SemanticIndexer(use_embeddings=True)
    n = indexer.index_file(str(src), SAMPLE)
    assert n >= 3
    results = indexer.search("how do we handle approvals?", top_k=3)
    assert results
    top = results[0]
    assert "approv" in top.symbol.lower() or "approv" in top.snippet.lower()
    assert top.score > 0
    again = indexer.search("how do we handle approvals?", top_k=3)
    assert [r.chunk_id for r in again] == [r.chunk_id for r in results]


def test_tfidf_fallback_without_embeddings(tmp_path: Path):
    src = tmp_path / "gate.py"
    src.write_text(SAMPLE, encoding="utf-8")
    indexer = SemanticIndexer(use_embeddings=False)
    indexer.index_file(str(src), SAMPLE)
    results = indexer.search("RBAC gate for approvals", top_k=2)
    assert results
    assert any("policy" in r.snippet.lower() or "approv" in r.symbol.lower() for r in results)


def test_index_directory_and_empty_query(tmp_path: Path):
    pkg = tmp_path / "pkg"
    pkg.mkdir()
    (pkg / "a.py").write_text("def alpha():\n    return 1\n", encoding="utf-8")
    (pkg / "b.py").write_text("def beta_network_socket():\n    return 2\n", encoding="utf-8")
    indexer = SemanticIndexer()
    total = indexer.index_directory(pkg)
    assert total >= 2
    assert indexer.chunk_count >= 2
    assert indexer.search("   ") == []
    hits = indexer.search("beta_network_socket", top_k=3)
    assert hits
    assert any("beta" in h.symbol.lower() or "socket" in h.snippet.lower() for h in hits)
