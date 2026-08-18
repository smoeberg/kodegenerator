"""AST/tokenize helpers for source-aware architecture validation."""
from __future__ import annotations

import io
import tokenize


def source_without_comments(source: str) -> str:
    """Return source with comments removed (strings preserved).

    Used by pattern constraints so that documented examples in comments do not
    create false positives, while real code tokens remain visible.
    """
    out: list[str] = []
    try:
        tokens = tokenize.generate_tokens(io.StringIO(source).readline)
        for tok in tokens:
            if tok.type == tokenize.COMMENT:
                continue
            out.append(tok.string)
    except tokenize.TokenError:
        # Fail open to raw source for matching — constraint evaluator still runs.
        return source
    return "".join(out)
