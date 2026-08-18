"""AST/tokenize helpers for source-aware architecture validation."""
from __future__ import annotations

import io
import tokenize


def source_without_comments(source: str) -> str:
    """Return source with comments removed (strings and whitespace preserved).

    Used by pattern constraints so that documented examples in comments do not
    create false positives, while real code tokens and spacing remain intact for
    regex matching (e.g. ``class\\s+Order``).
    """
    clean_tokens: list[tokenize.TokenInfo] = []
    try:
        tokens = tokenize.generate_tokens(io.StringIO(source).readline)
        for tok in tokens:
            if tok.type == tokenize.COMMENT:
                continue
            clean_tokens.append(tok)
        return tokenize.untokenize(clean_tokens)
    except (tokenize.TokenError, Exception):
        # Fail open to raw source for matching — constraint evaluator still runs.
        return source
