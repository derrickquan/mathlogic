"""Problem forms — the shapes a generated problem can take.

A form owns three things: which operands it needs, how to work out the answer,
and how the prompt is written. Everything else (which operands are legal, which
combinations are pedagogically useful) belongs to constraints.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Mapping

# The operator symbols the curriculum documents use. × and ÷ rather than * and
# /, because these strings are shown to a six-year-old.
TIMES = "×"
DIVIDE = "÷"


@dataclass(frozen=True)
class Form:
    spec: str
    operands: tuple[str, ...]
    symbol: str
    operation: Callable[[Mapping[str, int]], int | None]
    answer_shape: str = "integer"

    def evaluate(self, values: Mapping[str, int]) -> int | None:
        """The answer, or None where the form is undefined for these operands."""
        return self.operation(values)

    def render(self, values: Mapping[str, int]) -> str:
        """The prompt as stored on the problem row: '7 + 2'.

        The trailing '= _' of the form spec is not part of the prompt — the
        tablet draws the answer box itself.
        """
        return f"{values['a']} {self.symbol} {values['b']}"


def _add(v: Mapping[str, int]) -> int:
    return v["a"] + v["b"]


def _subtract(v: Mapping[str, int]) -> int:
    return v["a"] - v["b"]


def _multiply(v: Mapping[str, int]) -> int:
    return v["a"] * v["b"]


def _divide(v: Mapping[str, int]) -> int | None:
    if v["b"] == 0 or v["a"] % v["b"] != 0:
        return None
    return v["a"] // v["b"]


FORMS: dict[str, Form] = {
    form.spec: form
    for form in (
        Form("a + b = _", ("a", "b"), "+", _add),
        Form("a - b = _", ("a", "b"), "-", _subtract),
        Form(f"a {TIMES} b = _", ("a", "b"), TIMES, _multiply),
        Form(f"a {DIVIDE} b = _", ("a", "b"), DIVIDE, _divide),
    )
}


def form_for(spec: str) -> Form:
    try:
        return FORMS[spec]
    except KeyError:
        known = ", ".join(sorted(FORMS))
        raise ValueError(f"unknown form {spec!r}; known forms are {known}") from None
