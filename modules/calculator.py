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
from typing import Any, Callable

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


# ---- word problems: the model writes the expression, the app works it out ------------------------------

EXPRESSION_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {"expression": {"type": "string", "maxLength": 120}, "unit": {"type": "string", "maxLength": 30}},
    "required": ["expression", "unit"],
}
EXPRESSION_PROMPT = """Turn this question into one arithmetic expression that answers it. Use only the numbers
in the question and + - * / and parentheses. Do not work it out. If the question cannot be answered from
its own numbers, reply with an empty expression.

Question: {question}

Reply with one JSON object: {{"expression": "...", "unit": "the unit of the answer, or an empty string"}}"""
EXPRESSION_OPTIONS = {"temperature": 0.0, "num_predict": 60, "num_ctx": 2048}
_QUANTITY_QUESTION = re.compile(
    r"\b(how\s+(?:much|many|long|far|old)|what\s+is\s+the\s+(?:total|sum|difference|average|cost|price)|in\s+total|altogether|left|remain\w*|each|per|average|cost|change)\b",
    re.IGNORECASE,
)
# Numbers an expression may use without the question stating them: units and percent.
_STANDARD_NUMBERS = {"100", "60", "24", "7", "12", "365", "1000"}


def looks_like_word_problem(question: str) -> bool:
    """A short question with at least two numbers that asks for a quantity."""

    text = str(question or "")
    return len(text) <= 400 and len(re.findall(r"\d+(?:\.\d+)?", text)) >= 2 and bool(_QUANTITY_QUESTION.search(text))


def _numbers(text: str) -> list[str]:
    return [number.rstrip("0").rstrip(".") if "." in number else number for number in re.findall(r"\d+(?:\.\d+)?", _THOUSANDS.sub("", text))]


def solve_word_problem(question: str, ask: Callable[[str, dict[str, Any]], str]) -> Calculation | None:
    """Ask the model only for the expression, check it, and work it out exactly. None when that is not possible.

    The expression may use only numbers that are in the question (and units such as 100 or 60), so a
    model cannot bring in figures of its own. The answer shows the expression, so it can be checked.
    """

    import json

    try:
        reply = json.loads(ask(EXPRESSION_PROMPT.format(question=str(question).strip()), EXPRESSION_SCHEMA))
        expression = str(reply.get("expression") or "").strip()
        unit = str(reply.get("unit") or "").strip()
    except Exception:  # no model, or a reply that is not the promised shape: the model answers as usual
        return None
    if not expression or not _ALLOWED.match(expression.replace("×", "*").replace("÷", "/")):
        return None
    allowed = set(_numbers(question)) | _STANDARD_NUMBERS
    if any(number not in allowed for number in _numbers(expression)):
        return None
    found = calculate(f"what is {expression}")
    if found is None or found.value is None:
        return None
    answer = f"{found.answer}{(' ' + unit) if unit and not unit.startswith('$') else ''}"
    if unit.startswith("$") or "dollar" in unit.lower():
        answer = f"{found.answer} dollars"
    return Calculation(str(question).strip(), found.expression, found.value, f"{answer} (the model set up the calculation from the question; the app worked it out)")


__all__ = ["Calculation", "EXPRESSION_OPTIONS", "EXPRESSION_SCHEMA", "calculate", "looks_like_word_problem", "solve_word_problem"]
