"""Restricted evaluator for workflow transition conditions.

Workflow conditions are data, not Python programs. This evaluator intentionally
supports a small expression language and never executes arbitrary Python code.
"""

from __future__ import annotations

import ast
import operator
from typing import Any, Mapping


class ConditionEvaluationError(ValueError):
    """Raised when a workflow condition is invalid or unsafe."""


_BIN_OPS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.Mod: operator.mod,
}
_CMP_OPS = {
    ast.Eq: operator.eq,
    ast.NotEq: operator.ne,
    ast.Lt: operator.lt,
    ast.LtE: operator.le,
    ast.Gt: operator.gt,
    ast.GtE: operator.ge,
    ast.In: operator.contains,
    ast.NotIn: lambda a, b: not operator.contains(a, b),
}


class ConditionEvaluator:
    """Evaluate a deliberately restricted boolean expression language."""

    def evaluate(self, expression: str, context: Mapping[str, Any]) -> bool:
        if not expression or len(expression) > 512:
            raise ConditionEvaluationError("Condition must contain 1-512 characters")
        try:
            tree = ast.parse(expression, mode="eval")
            return bool(self._eval(tree.body, context))
        except (SyntaxError, TypeError, ValueError, KeyError, ZeroDivisionError) as exc:
            raise ConditionEvaluationError("Invalid workflow condition") from exc

    def _eval(self, node: ast.AST, context: Mapping[str, Any]) -> Any:
        if isinstance(node, ast.Constant) and isinstance(node.value, (str, int, float, bool, type(None))):
            return node.value
        if isinstance(node, ast.Name):
            if node.id not in context:
                raise KeyError(node.id)
            return context[node.id]
        if isinstance(node, ast.List):
            return [self._eval(item, context) for item in node.elts]
        if isinstance(node, ast.Tuple):
            return tuple(self._eval(item, context) for item in node.elts)
        if isinstance(node, ast.Dict):
            return {
                self._eval(key, context): self._eval(value, context)
                for key, value in zip(node.keys, node.values)
            }
        if isinstance(node, ast.Attribute):
            if node.attr.startswith("_"):
                raise ConditionEvaluationError("Private attributes are forbidden")
            value = self._eval(node.value, context)
            if isinstance(value, Mapping):
                return value[node.attr]
            if not hasattr(value, node.attr):
                raise KeyError(node.attr)
            return getattr(value, node.attr)
        if isinstance(node, ast.Subscript):
            value = self._eval(node.value, context)
            key = self._eval(node.slice, context)
            return value[key]
        if isinstance(node, ast.BoolOp):
            values = [self._eval(value, context) for value in node.values]
            if isinstance(node.op, ast.And):
                return all(values)
            if isinstance(node.op, ast.Or):
                return any(values)
            raise ConditionEvaluationError("Boolean operator not allowed")
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.Not, ast.USub, ast.UAdd)):
            value = self._eval(node.operand, context)
            if isinstance(node.op, ast.Not):
                return not value
            return -value if isinstance(node.op, ast.USub) else +value
        if isinstance(node, ast.BinOp) and type(node.op) in _BIN_OPS:
            return _BIN_OPS[type(node.op)](self._eval(node.left, context), self._eval(node.right, context))
        if isinstance(node, ast.Compare):
            left = self._eval(node.left, context)
            for op, comparator in zip(node.ops, node.comparators):
                if type(op) not in _CMP_OPS:
                    raise ConditionEvaluationError("Comparison operator not allowed")
                right = self._eval(comparator, context)
                if not _CMP_OPS[type(op)](left, right):
                    return False
                left = right
            return True
        raise ConditionEvaluationError(f"Expression node {type(node).__name__} is not allowed")
