"""Exact answers to plain arithmetic, so that "what is 7 times 6?" does not depend on a model's sampling.

Measured on 2026-11-23: through the chat, the local 8B model answered "What is 7 times 6?" with 84
once in three tries. A question that is nothing but arithmetic ("what is 17 times 23", "15% of
80", "-15 plus 8", "3.5 x 2.4", "(4 + 6) / 4") is answered here instead, exactly, and the answer
says it was calculated by the app. Anything else, word problems included, still goes to the model:
pulling numbers out of a sentence is the model's job, and guessing at it here would be worse.

Only numbers, + - * / ** and parentheses are evaluated, by walking the expression's syntax tree;
nothing is passed to eval.
"""

from __future__ import annotations

import ast
import operator
import re
from dataclasses import dataclass
from typing import Any

_ASKED = re.compile(r"^\s*(?:please\s+)?(?:what\s+is|what's|whats|calculate|compute|evaluate|work\s+out|how\s+much\s+is|solve)\s*:?\s*(?P<expr>.+?)\s*(?:=\s*)?[?.!]*\s*$", re.IGNORECASE)
_BARE = re.compile(r"^\s*(?P<expr>[-+(]*\d[\d\s.,+\-*/x×÷^()%]*?)\s*(?:=\s*\??)?\s*[?.!]*\s*$", re.IGNORECASE)
_PERCENT_OF = re.compile(r"(-?\d+(?:\.\d+)?)\s*(?:%|percent)\s+of\s+(-?\d+(?:\.\d+)?)", re.IGNORECASE)
_SQUARE_ROOT = re.compile(r"(?:the\s+)?square\s+root\s+of\s+(\d+(?:\.\d+)?)", re.IGNORECASE)
_THOUSANDS = re.compile(r"(?<=\d),(?=\d{3}\b)")
_WORDS = (
    (re.compile(r"\bmultiplied\s+by\b", re.I), "*"),
    (re.compile(r"\btimes\b", re.I), "*"),
    (re.compile(r"(?<=[\d)\s])x(?=[\s\d(-])", re.I), "*"),
    (re.compile(r"[×·]"), "*"),
    (re.compile(r"\bdivided\s+by\b", re.I), "/"),
    (re.compile(r"\bover\b", re.I), "/"),
    (re.compile(r"÷"), "/"),
    (re.compile(r"\bplus\b|\badded\s+to\b", re.I), "+"),
    (re.compile(r"\bminus\b|−", re.I), "-"),
    (re.compile(r"\bnegative\s+", re.I), "-"),
    (re.compile(r"\bto\s+the\s+power\s+of\b|\^", re.I), "**"),
    (re.compile(r"\bsquared\b", re.I), "**2"),
    (re.compile(r"\bcubed\b", re.I), "**3"),
)
_ALLOWED = re.compile(r"^[\d\s.+\-*/()]+$")
_OPERATORS: dict[type, Any] = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul, ast.Div: operator.truediv, ast.Pow: operator.pow}


@dataclass(frozen=True)
class Calculation:
    question: str
    expression: str
    value: float | int | None
    answer: str

    def to_dict(self) -> dict[str, Any]:
        return {"question": self.question, "expression": self.expression, "value": self.value, "answer": self.answer}


def _evaluate(node: ast.AST) -> float | int:
    if isinstance(node, ast.Expression):
        return _evaluate(node.body)
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)) and not isinstance(node.value, bool):
        return node.value
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.USub, ast.UAdd)):
        value = _evaluate(node.operand)
        return -value if isinstance(node.op, ast.USub) else value
    if isinstance(node, ast.BinOp) and type(node.op) in _OPERATORS:
        left, right = _evaluate(node.left), _evaluate(node.right)
        if isinstance(node.op, ast.Pow) and (abs(right) > 64 or abs(left) > 1e6):
            raise ValueError("too large to work out here")
        return _OPERATORS[type(node.op)](left, right)
    raise ValueError("not plain arithmetic")


def _plain(value: float | int) -> str:
    if isinstance(value, float):
        if value.is_integer() and abs(value) < 1e15:
            return str(int(value))
        return f"{round(value, 10):.10f}".rstrip("0").rstrip(".")
    return str(value)


def _shown(expression: str) -> str:
    return re.sub(r"\s+", " ", expression.replace("**", "^").replace("*", " × ").replace("/", " ÷ ").replace("+", " + ")).replace("( ", "(").replace(" )", ")").strip()


def calculate(question: str) -> Calculation | None:
    """The exact answer when the question is nothing but arithmetic, else None (the model answers)."""

    text = str(question or "").strip()
    if not text or len(text) > 200:
        return None
    match = _ASKED.match(text) or _BARE.match(text)
    if not match:
        return None
    expression = _THOUSANDS.sub("", match.group("expr"))
    expression = _PERCENT_OF.sub(r"(\1 / 100 * \2)", expression)
    expression = _SQUARE_ROOT.sub(r"(\1 ** 0.5)", expression)
    expression = re.sub(r"(\d+(?:\.\d+)?)\s*%", r"(\1 / 100)", expression)
    for pattern, symbol in _WORDS:
        expression = pattern.sub(f" {symbol} ", expression)
    expression = re.sub(r"\s+", " ", expression).strip()
    # "- 15 + 8" from "minus 15 plus 8" at the start is a negative number.
    if not _ALLOWED.match(expression) or len(re.findall(r"\d+(?:\.\d+)?", expression)) < 2 or not re.search(r"[+\-*/]", expression.lstrip("-( ")):
        return None
    try:
        value = _evaluate(ast.parse(expression, mode="eval"))
    except ZeroDivisionError:
        return Calculation(text, expression, None, f"{_shown(expression)} has no answer: it divides by zero.")
    except (SyntaxError, ValueError, OverflowError, TypeError):
        return None
    shown = _plain(value)
    return Calculation(text, expression, int(shown) if re.fullmatch(r"-?\d+", shown) else float(shown), f"{_shown(expression)} = {shown}")


__all__ = ["Calculation", "calculate"]
