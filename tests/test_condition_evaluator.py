"""Security tests for workflow condition evaluation."""

import pytest

from domain.condition_evaluator import ConditionEvaluationError, ConditionEvaluator


@pytest.fixture
def evaluator():
    return ConditionEvaluator()


def test_safe_comparison(evaluator):
    assert evaluator.evaluate("test_coverage >= 0.9", {"test_coverage": 0.95}) is True
    assert evaluator.evaluate("test_coverage >= 0.9", {"test_coverage": 0.75}) is False


def test_safe_boolean_expression(evaluator):
    context = {"test_coverage": 0.95, "consensus_score": 0.85}
    assert evaluator.evaluate(
        "test_coverage >= 0.9 and consensus_score >= 0.8", context
    ) is True


def test_attribute_access_is_limited_to_public_attributes():
    class Actor:
        type = "human"

    assert ConditionEvaluator().evaluate("actor.type == 'human'", {"actor": Actor()})


def test_function_calls_are_rejected(evaluator):
    with pytest.raises(ConditionEvaluationError):
        evaluator.evaluate("__import__('os').system('echo unsafe')", {})


def test_private_attributes_are_rejected(evaluator):
    with pytest.raises(ConditionEvaluationError):
        evaluator.evaluate("actor.__class__", {"actor": object()})


def test_unknown_names_are_rejected(evaluator):
    with pytest.raises(ConditionEvaluationError):
        evaluator.evaluate("unknown_value == 1", {})


def test_expression_size_is_bounded(evaluator):
    with pytest.raises(ConditionEvaluationError):
        evaluator.evaluate("a" * 513, {})
