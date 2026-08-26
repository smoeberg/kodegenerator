"""Lightweight vector store with in-memory and SQLite backends.

Supports small fixed-dimension embeddings and cosine similarity. No external
vector database is required. Used by :class:`services.semantic_indexer.SemanticIndexer`.
"""
from __future__ import annotations

import json
import math
import sqlite3
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional, Sequence


def cosine_similarity(a: Sequence[float], b: Sequence[float]) -> float:
    """Return cosine similarity in ``[-1, 1]``; 0.0 for zero vectors."""
    if len(a) != len(b):
        raise ValueError("vector dimensions must match")
    dot = 0.0
    na = 0.0
    nb = 0.0
    for x, y in zip(a, b):
        dot += x * y
        na += x * x
        nb += y * y
    if na <= 0.0 or nb <= 0.0:
        return 0.0
    return dot / (math.sqrt(na) * math.sqrt(nb))


@dataclass(frozen=True)
class VectorRecord:
    record_id: str
    vector: tuple[float, ...]
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class SearchHit:
    record_id: str
    score: float
    metadata: dict[str, Any]


class VectorStore:
    def upsert(self, record_id: str, vector: Sequence[float], metadata: Optional[dict[str, Any]] = None) -> None:
        raise NotImplementedError

    def delete(self, record_id: str) -> None:
        raise NotImplementedError

    def search(self, query: Sequence[float], *, top_k: int = 5) -> list[SearchHit]:
        raise NotImplementedError

    def count(self) -> int:
        raise NotImplementedError


class InMemoryVectorStore(VectorStore):
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._records: dict[str, VectorRecord] = {}

    def upsert(self, record_id: str, vector: Sequence[float], metadata: Optional[dict[str, Any]] = None) -> None:
        with self._lock:
            self._records[record_id] = VectorRecord(
                record_id=record_id,
                vector=tuple(float(x) for x in vector),
                metadata=dict(metadata or {}),
            )

    def delete(self, record_id: str) -> None:
        with self._lock:
            self._records.pop(record_id, None)

    def search(self, query: Sequence[float], *, top_k: int = 5) -> list[SearchHit]:
        if top_k < 1:
            return []
        q = tuple(float(x) for x in query)
        with self._lock:
            scored = [
                SearchHit(
                    record_id=rec.record_id,
                    score=cosine_similarity(q, rec.vector),
                    metadata=dict(rec.metadata),
                )
                for rec in self._records.values()
            ]
        scored.sort(key=lambda h: (-h.score, h.record_id))
        return scored[:top_k]

    def count(self) -> int:
        with self._lock:
            return len(self._records)


class SQLiteVectorStore(VectorStore):
    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(str(self.path), check_same_thread=False)
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS vectors (
                record_id TEXT PRIMARY KEY,
                vector_json TEXT NOT NULL,
                metadata_json TEXT NOT NULL
            )
            """
        )
        self._conn.commit()

    def upsert(self, record_id: str, vector: Sequence[float], metadata: Optional[dict[str, Any]] = None) -> None:
        with self._lock:
            self._conn.execute(
                """
                INSERT INTO vectors(record_id, vector_json, metadata_json)
                VALUES (?, ?, ?)
                ON CONFLICT(record_id) DO UPDATE SET
                    vector_json=excluded.vector_json,
                    metadata_json=excluded.metadata_json
                """,
                (
                    record_id,
                    json.dumps([float(x) for x in vector]),
                    json.dumps(dict(metadata or {})),
                ),
            )
            self._conn.commit()

    def delete(self, record_id: str) -> None:
        with self._lock:
            self._conn.execute("DELETE FROM vectors WHERE record_id = ?", (record_id,))
            self._conn.commit()

    def search(self, query: Sequence[float], *, top_k: int = 5) -> list[SearchHit]:
        if top_k < 1:
            return []
        q = [float(x) for x in query]
        with self._lock:
            rows = self._conn.execute(
                "SELECT record_id, vector_json, metadata_json FROM vectors"
            ).fetchall()
        hits: list[SearchHit] = []
        for record_id, vector_json, metadata_json in rows:
            vec = json.loads(vector_json)
            meta = json.loads(metadata_json)
            hits.append(
                SearchHit(
                    record_id=record_id,
                    score=cosine_similarity(q, vec),
                    metadata=meta,
                )
            )
        hits.sort(key=lambda h: (-h.score, h.record_id))
        return hits[:top_k]

    def count(self) -> int:
        with self._lock:
            row = self._conn.execute("SELECT COUNT(*) FROM vectors").fetchone()
            return int(row[0]) if row else 0

    def close(self) -> None:
        with self._lock:
            self._conn.close()
