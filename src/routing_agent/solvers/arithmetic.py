"""Safe arithmetic solver: AST-based evaluation with a strict node whitelist.

Supports +, -, *, /, //, %, **, parentheses, unary +/-, decimals, and a small
set of worded forms ("what is 17% of 340", "sum of 4 and 9"). Never uses
`eval`/`exec` — expressions are parsed with `ast.parse` and walked against an
explicit allowlist of node types and operators, rejecting anything else
(names, calls, attribute access, comprehensions, etc.) to stay safe against
adversarial input.
"""

from __future__ import annotations

import ast
import operator
import re

from routing_agent.classifier import TaskType
from routing_agent.models import Task
from routing_agent.solvers import SolverResult

_BIN_OPS: dict[type[ast.operator], object] = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
}
_UNARY_OPS: dict[type[ast.unaryop], object] = {
    ast.UAdd: operator.pos,
    ast.USub: operator.neg,
}

_MAX_EXPONENT = 1000  # guard against pathological ** blowups
_MAX_ABS_RESULT = 1e18

_PERCENT_OF_RE = re.compile(
    r"(?P<pct>\d+(?:\.\d+)?)\s*%\s*of\s+(?P<base>\d+(?:\.\d+)?)", re.IGNORECASE
)
_QUESTION_STRIP_RE = re.compile(r"^(what\s+is|calculate|compute|evaluate)\s*:?\s*", re.IGNORECASE)
_TRAILING_STRIP_RE = re.compile(r"[?.!\s]+$")


class _UnsafeExpression(Exception):
    """Raised when the expression contains a disallowed AST node."""


def _eval_node(node: ast.AST) -> float:
    if isinstance(node, ast.Expression):
        return _eval_node(node.body)
    if isinstance(node, ast.Constant):
        if isinstance(node.value, int | float) and not isinstance(node.value, bool):
            return node.value
        raise _UnsafeExpression(f"disallowed constant: {node.value!r}")
    if isinstance(node, ast.BinOp):
        op_fn = _BIN_OPS.get(type(node.op))
        if op_fn is None:
            raise _UnsafeExpression(f"disallowed operator: {type(node.op).__name__}")
        left = _eval_node(node.left)
        right = _eval_node(node.right)
        if isinstance(node.op, ast.Pow) and abs(right) > _MAX_EXPONENT:
            raise _UnsafeExpression("exponent too large")
        result = op_fn(left, right)
        if abs(result) > _MAX_ABS_RESULT:
            raise _UnsafeExpression("result magnitude too large")
        return result
    if isinstance(node, ast.UnaryOp):
        op_fn = _UNARY_OPS.get(type(node.op))
        if op_fn is None:
            raise _UnsafeExpression(f"disallowed unary operator: {type(node.op).__name__}")
        return op_fn(_eval_node(node.operand))
    raise _UnsafeExpression(f"disallowed node: {type(node).__name__}")


def _safe_eval(expression: str) -> float | None:
    try:
        tree = ast.parse(expression, mode="eval")
        return _eval_node(tree)
    except (SyntaxError, ZeroDivisionError, _UnsafeExpression, RecursionError):
        return None


def _format_result(value: float) -> str:
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(round(value, 10)).rstrip("0").rstrip(".") if isinstance(value, float) else str(value)


def _extract_expression(prompt: str) -> str | None:
    text = _QUESTION_STRIP_RE.sub("", prompt.strip())
    text = _TRAILING_STRIP_RE.sub("", text)
    if not text:
        return None
    # Reject anything containing letters (worded forms handled separately).
    if re.search(r"[a-zA-Z]", text):
        return None
    if not re.search(r"\d", text):
        return None
    return text


def try_solve(task: Task, task_type: TaskType) -> SolverResult:
    """Attempt to solve an arithmetic task with a safe AST evaluator.

    Returns confident=True only for clean numeric expressions or the
    "X% of Y" worded form; anything ambiguous (extra prose, multiple
    questions, unsupported functions) yields confident=False.
    """
    if task_type != TaskType.ARITHMETIC:
        return SolverResult(answer=None, confident=False)

    prompt = task.prompt.strip()

    percent_match = _PERCENT_OF_RE.fullmatch(
        _TRAILING_STRIP_RE.sub("", _QUESTION_STRIP_RE.sub("", prompt.strip()))
    )
    if percent_match:
        pct = float(percent_match.group("pct"))
        base = float(percent_match.group("base"))
        value = (pct / 100.0) * base
        return SolverResult(answer=_format_result(value), confident=True)

    expression = _extract_expression(prompt)
    if expression is None:
        return SolverResult(answer=None, confident=False)

    value = _safe_eval(expression)
    if value is None:
        return SolverResult(answer=None, confident=False)

    return SolverResult(answer=_format_result(value), confident=True)
