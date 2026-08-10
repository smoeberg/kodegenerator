"""Explicit proof that P5-02 cannot become verification authority."""

import ast
from pathlib import Path
import sys

SLICE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SLICE))

from handoff import VerificationHandoffEngine  # noqa: E402


def test_engine_exposes_only_handoff_operations():
    assert hasattr(VerificationHandoffEngine, "prepare")
    assert hasattr(VerificationHandoffEngine, "dispatch")
    assert hasattr(VerificationHandoffEngine, "bind_response")
    assert not hasattr(VerificationHandoffEngine, "verify")
    assert not hasattr(VerificationHandoffEngine, "create_decision")


def test_handoff_source_does_not_construct_p3_20_decisions():
    tree = ast.parse((SLICE / "handoff.py").read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            assert node.id not in {"VerificationDecision", "CriterionResult"}
