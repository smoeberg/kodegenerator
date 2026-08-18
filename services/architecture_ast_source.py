"""Token helpers for source-aware architecture pattern matching.

Preserves character offsets (and therefore line numbers) by blanking tokens
instead of deleting them. Supports match modes:

- include_strings (default): strip # comments only
- code_only: strip # comments and docstrings / module string literals
"""
from __future__ import annotations

import io
import tokenize
from typing import Literal

MatchMode = Literal["include_strings", "code_only"]


def source_without_comments(source: str) -> str:
    """Return source with comments removed via untokenize (legacy helper).

    Prefer ``prepare_pattern_source`` when line numbers are required.
    """
    return prepare_pattern_source(source, match_mode="include_strings")


def prepare_pattern_source(
    source: str,
    *,
    match_mode: MatchMode = "include_strings",
) -> str:
    """Return source prepared for regex matching while preserving offsets.

    Comments (and optionally docstrings) are replaced with spaces of the same
    length so ``re.Match.start()`` still maps to the original line number.
    """
    if match_mode not in {"include_strings", "code_only"}:
        match_mode = "include_strings"

    try:
        tokens = list(tokenize.generate_tokens(io.StringIO(source).readline))
    except (tokenize.TokenError, Exception):
        return source

    chars = list(source)

    def blank_span(start: tuple[int, int], end: tuple[int, int]) -> None:
        # tokenize positions are 1-based rows; convert to absolute offset.
        abs_start = _offset(source, start)
        abs_end = _offset(source, end)
        for i in range(abs_start, min(abs_end, len(chars))):
            if chars[i] != "\n":
                chars[i] = " "

    prev_was_indent_or_start = True
    for i, tok in enumerate(tokens):
        if tok.type == tokenize.COMMENT:
            blank_span(tok.start, tok.end)
            continue

        if match_mode == "code_only" and tok.type == tokenize.STRING:
            # Docstring heuristic: string at module/class/function start.
            if prev_was_indent_or_start or _is_likely_docstring(tokens, i):
                blank_span(tok.start, tok.end)

        if tok.type in {
            tokenize.INDENT,
            tokenize.DEDENT,
            tokenize.NEWLINE,
            tokenize.NL,
            tokenize.ENCODING,
        }:
            prev_was_indent_or_start = True
        elif tok.type == tokenize.STRING and prev_was_indent_or_start:
            prev_was_indent_or_start = False
        elif tok.type not in {tokenize.NL, tokenize.COMMENT}:
            prev_was_indent_or_start = tok.type in {
                tokenize.INDENT,
                tokenize.NEWLINE,
            }

    return "".join(chars)


def _offset(source: str, pos: tuple[int, int]) -> int:
    row, col = pos
    if row <= 1:
        return col
    lines = source.splitlines(keepends=True)
    # row is 1-based
    prefix = sum(len(lines[i]) for i in range(min(row - 1, len(lines))))
    return prefix + col


def _is_likely_docstring(tokens: list[tokenize.TokenInfo], index: int) -> bool:
    """True when STRING is the first statement in a suite (classic docstring)."""
    # Look backward past NL/INDENT/DEDENT/ENCODING for NEWLINE or start.
    j = index - 1
    while j >= 0 and tokens[j].type in {
        tokenize.INDENT,
        tokenize.DEDENT,
        tokenize.NL,
        tokenize.ENCODING,
        tokenize.COMMENT,
    }:
        j -= 1
    if j < 0:
        return True
    return tokens[j].type == tokenize.NEWLINE


def line_number_at(source: str, absolute_offset: int) -> int:
    """1-based line number for an absolute character offset."""
    if absolute_offset <= 0:
        return 1
    return source.count("\n", 0, absolute_offset) + 1
