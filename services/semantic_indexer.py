"""Semantic code search via chunking, embeddings and TF-IDF fallback.

Chunks Python (and generic text) sources into symbol-level units, embeds them
with a deterministic hashing encoder (no external model required) or falls
back to TF-IDF / BM25-like lexical scoring when embeddings are disabled.
"""
from __future__ import annotations

import ast
import hashlib
import logging
import math
import re
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Optional, Sequence

from services.vector_store import InMemoryVectorStore, VectorStore

logger = logging.getLogger(__name__)

_TOKEN_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]{1,64}")
_DEFAULT_DIM = 64


@dataclass(frozen=True)
class CodeChunk:
    chunk_id: str
    path: str
    symbol: str
    kind: str
    start_line: int
    end_line: int
    text: str

    def snippet(self, max_chars: int = 240) -> str:
        text = self.text.strip()
        if len(text) <= max_chars:
            return text
        return text[: max_chars - 3] + "..."


@dataclass(frozen=True)
class SearchResult:
    path: str
    symbol: str
    kind: str
    snippet: str
    score: float
    start_line: int
    end_line: int
    chunk_id: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "symbol": self.symbol,
            "kind": self.kind,
            "snippet": self.snippet,
            "score": round(self.score, 6),
            "start_line": self.start_line,
            "end_line": self.end_line,
            "chunk_id": self.chunk_id,
        }


def tokenize(text: str) -> list[str]:
    return [m.group(0).lower() for m in _TOKEN_RE.finditer(text)]


def hash_embed(text: str, *, dim: int = _DEFAULT_DIM) -> list[float]:
    """Deterministic feature-hashing embedding (no external model)."""
    if dim < 4:
        raise ValueError("dim must be >= 4")
    vec = [0.0] * dim
    tokens = tokenize(text)
    if not tokens:
        return vec
    for token in tokens:
        digest = hashlib.blake2b(token.encode("utf-8"), digest_size=8).digest()
        idx = int.from_bytes(digest[:4], "big") % dim
        sign = 1.0 if digest[4] % 2 == 0 else -1.0
        vec[idx] += sign
    norm = math.sqrt(sum(x * x for x in vec))
    if norm > 0:
        vec = [x / norm for x in vec]
    return vec


def chunk_python_source(path: str, source: str) -> list[CodeChunk]:
    chunks: list[CodeChunk] = []
    lines = source.splitlines()
    try:
        tree = ast.parse(source)
    except SyntaxError:
        text = source.strip()
        if text:
            chunks.append(
                CodeChunk(
                    chunk_id=f"{path}::module",
                    path=path,
                    symbol=Path(path).stem,
                    kind="block",
                    start_line=1,
                    end_line=max(1, len(lines)),
                    text=text[:4000],
                )
            )
        return chunks

    mod_doc = ast.get_docstring(tree)
    if mod_doc:
        chunks.append(
            CodeChunk(
                chunk_id=f"{path}::docstring",
                path=path,
                symbol=Path(path).stem,
                kind="docstring",
                start_line=1,
                end_line=1,
                text=mod_doc,
            )
        )

    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            chunks.append(_chunk_from_node(path, lines, node, kind="function"))
        elif isinstance(node, ast.ClassDef):
            chunks.append(_chunk_from_node(path, lines, node, kind="class"))
            for child in node.body:
                if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    chunks.append(
                        _chunk_from_node(
                            path, lines, child, kind="function", symbol_prefix=f"{node.name}."
                        )
                    )

    if not chunks and source.strip():
        chunks.append(
            CodeChunk(
                chunk_id=f"{path}::module",
                path=path,
                symbol=Path(path).stem,
                kind="module",
                start_line=1,
                end_line=max(1, len(lines)),
                text=source.strip()[:4000],
            )
        )
    return chunks


def _chunk_from_node(
    path: str,
    lines: list[str],
    node: ast.AST,
    *,
    kind: str,
    symbol_prefix: str = "",
) -> CodeChunk:
    name = getattr(node, "name", kind)
    start = getattr(node, "lineno", 1)
    end = getattr(node, "end_lineno", start) or start
    text = "\n".join(lines[start - 1 : end])
    doc = ast.get_docstring(node) or ""
    payload = text if len(text) < 4000 else text[:4000]
    if doc and doc not in payload:
        payload = doc + "\n" + payload
    symbol = f"{symbol_prefix}{name}"
    return CodeChunk(
        chunk_id=f"{path}::{symbol}",
        path=path,
        symbol=symbol,
        kind=kind,
        start_line=start,
        end_line=end,
        text=payload,
    )


class _TfidfIndex:
    def __init__(self, *, k1: float = 1.5, b: float = 0.75) -> None:
        self.k1 = k1
        self.b = b
        self._docs: dict[str, list[str]] = {}
        self._df: dict[str, int] = {}
        self._avgdl = 0.0

    def upsert(self, doc_id: str, text: str) -> None:
        tokens = tokenize(text)
        old = self._docs.pop(doc_id, None)
        if old:
            for t in set(old):
                self._df[t] = max(0, self._df.get(t, 0) - 1)
        self._docs[doc_id] = tokens
        for t in set(tokens):
            self._df[t] = self._df.get(t, 0) + 1
        total = sum(len(v) for v in self._docs.values())
        self._avgdl = total / max(1, len(self._docs))

    def delete(self, doc_id: str) -> None:
        old = self._docs.pop(doc_id, None)
        if not old:
            return
        for t in set(old):
            self._df[t] = max(0, self._df.get(t, 0) - 1)

    def search(self, query: str, *, top_k: int = 5) -> list[tuple[str, float]]:
        q_tokens = tokenize(query)
        if not q_tokens or not self._docs:
            return []
        n = len(self._docs)
        scores: list[tuple[str, float]] = []
        for doc_id, tokens in self._docs.items():
            tf: dict[str, int] = {}
            for t in tokens:
                tf[t] = tf.get(t, 0) + 1
            dl = len(tokens) or 1
            score = 0.0
            for qt in q_tokens:
                if qt not in tf:
                    continue
                df = self._df.get(qt, 0) or 1
                idf = math.log(1.0 + (n - df + 0.5) / (df + 0.5))
                freq = tf[qt]
                denom = freq + self.k1 * (1.0 - self.b + self.b * dl / max(self._avgdl, 1.0))
                score += idf * (freq * (self.k1 + 1.0)) / denom
            if score > 0:
                scores.append((doc_id, score))
        scores.sort(key=lambda x: (-x[1], x[0]))
        return scores[:top_k]


class SemanticIndexer:
    """Index source files and answer semantic / lexical search queries."""

    def __init__(
        self,
        store: Optional[VectorStore] = None,
        *,
        use_embeddings: bool = True,
        embedding_dim: int = _DEFAULT_DIM,
        cache_size: int = 64,
        embed_fn: Optional[Callable[[str], list[float]]] = None,
    ) -> None:
        self.store = store or InMemoryVectorStore()
        self.use_embeddings = use_embeddings
        self.embedding_dim = embedding_dim
        self.embed_fn = embed_fn or (lambda t: hash_embed(t, dim=embedding_dim))
        self._tfidf = _TfidfIndex()
        self._chunks: dict[str, CodeChunk] = {}
        self._lock = threading.RLock()
        self._cache: dict[str, list[SearchResult]] = {}
        self._cache_size = max(1, cache_size)

    def index_file(self, path: str, source: Optional[str] = None) -> int:
        if source is None:
            source = Path(path).read_text(encoding="utf-8", errors="replace")
        if path.endswith(".py"):
            chunks = chunk_python_source(path, source)
        else:
            chunks = [
                CodeChunk(
                    chunk_id=f"{path}::block",
                    path=path,
                    symbol=Path(path).stem,
                    kind="block",
                    start_line=1,
                    end_line=source.count("\n") + 1,
                    text=source[:4000],
                )
            ]
        with self._lock:
            for chunk in chunks:
                self._chunks[chunk.chunk_id] = chunk
                self._tfidf.upsert(chunk.chunk_id, f"{chunk.symbol} {chunk.text}")
                if self.use_embeddings:
                    vec = self.embed_fn(f"{chunk.symbol}\n{chunk.text}")
                    self.store.upsert(
                        chunk.chunk_id,
                        vec,
                        metadata={
                            "path": chunk.path,
                            "symbol": chunk.symbol,
                            "kind": chunk.kind,
                            "start_line": chunk.start_line,
                            "end_line": chunk.end_line,
                        },
                    )
            self._cache.clear()
        return len(chunks)

    def index_directory(
        self, root: Path | str, *, patterns: Sequence[str] = ("**/*.py",)
    ) -> int:
        root = Path(root)
        total = 0
        for pattern in patterns:
            for path in sorted(root.glob(pattern)):
                if path.is_file():
                    try:
                        total += self.index_file(str(path))
                    except OSError as exc:
                        logger.warning("skip %s: %s", path, exc)
        return total

    def search(self, query: str, *, top_k: int = 5) -> list[SearchResult]:
        if not query or not query.strip():
            return []
        cache_key = f"{query.strip()}::{top_k}"
        with self._lock:
            cached = self._cache.get(cache_key)
            if cached is not None:
                return list(cached)

        if self.use_embeddings and self.store.count() > 0:
            results = self._search_vector(query, top_k=top_k)
        else:
            results = self._search_lexical(query, top_k=top_k)

        with self._lock:
            if len(self._cache) >= self._cache_size:
                try:
                    self._cache.pop(next(iter(self._cache)))
                except StopIteration:
                    pass
            self._cache[cache_key] = list(results)
        return results

    def _search_vector(self, query: str, *, top_k: int) -> list[SearchResult]:
        qvec = self.embed_fn(query)
        hits = self.store.search(qvec, top_k=top_k)
        lex = {doc_id: score for doc_id, score in self._tfidf.search(query, top_k=top_k * 3)}
        max_lex = max(lex.values()) if lex else 1.0
        out: list[SearchResult] = []
        for hit in hits:
            chunk = self._chunks.get(hit.record_id)
            if chunk is None:
                continue
            lex_score = (lex.get(hit.record_id, 0.0) / max_lex) if max_lex else 0.0
            score = 0.7 * max(0.0, hit.score) + 0.3 * lex_score
            out.append(
                SearchResult(
                    path=chunk.path,
                    symbol=chunk.symbol,
                    kind=chunk.kind,
                    snippet=chunk.snippet(),
                    score=score,
                    start_line=chunk.start_line,
                    end_line=chunk.end_line,
                    chunk_id=chunk.chunk_id,
                )
            )
        out.sort(key=lambda r: (-r.score, r.path, r.symbol))
        return out[:top_k]

    def _search_lexical(self, query: str, *, top_k: int) -> list[SearchResult]:
        scored = self._tfidf.search(query, top_k=top_k)
        out: list[SearchResult] = []
        for doc_id, score in scored:
            chunk = self._chunks.get(doc_id)
            if chunk is None:
                continue
            out.append(
                SearchResult(
                    path=chunk.path,
                    symbol=chunk.symbol,
                    kind=chunk.kind,
                    snippet=chunk.snippet(),
                    score=score,
                    start_line=chunk.start_line,
                    end_line=chunk.end_line,
                    chunk_id=chunk.chunk_id,
                )
            )
        return out

    @property
    def chunk_count(self) -> int:
        with self._lock:
            return len(self._chunks)
