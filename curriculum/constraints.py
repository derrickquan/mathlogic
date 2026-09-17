"""The constraint vocabulary.

Operand ranges alone produce problems that skip the point of the level: a level
teaching addition within 10 must exclude sums of 11, or it is silently teaching
the next level. Constraints are where the pedagogy lives.

Two kinds, and the difference matters to the generator:

  * A **problem constraint** judges one problem on its own. It filters the pool
    of candidates before any page is drawn, so it can never fail at draw time.
  * A **page constraint** judges a whole page — it is about the shape of the
    set, not any one member. The generator draws, checks, and redraws.

Written as strings in the template so a band's config round-trips through the
`page_templates.constraints` jsonb column unchanged.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Mapping, Protocol, Sequence

from .forms import DIVIDE, TIMES, Form


class ProblemConstraint(Protocol):
    source: str

    def holds(self, form: Form, values: Mapping[str, int], result: int) -> bool: ...


class PageConstraint(Protocol):
    source: str

    def holds(self, page: Sequence[Mapping[str, int]]) -> bool: ...


# --------------------------------------------------------------------------
# Problem constraints
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class ResultBound:
    """`sum <= 10`, `product <= 81`, `result >= 5`.

    'sum' and 'product' are the same test as 'result' — they read better next to
    the form they constrain, and the curriculum documents use them.
    """

    source: str
    operator: str
    bound: int

    def holds(self, form: Form, values: Mapping[str, int], result: int) -> bool:
        if self.operator == "<=":
            return result <= self.bound
        if self.operator == ">=":
            return result >= self.bound
        if self.operator == "<":
            return result < self.bound
        if self.operator == ">":
            return result > self.bound
        if self.operator == "==":
            return result == self.bound
        raise ValueError(f"unsupported comparison {self.operator!r}")


@dataclass(frozen=True)
class ResultPositive:
    """Prevents negatives before they are taught.

    Zero is allowed: 5 - 5 is a fine problem for a level that has not met
    negative numbers, and the stated purpose of this constraint in the
    curriculum document is preventing negatives, not preventing zero.
    """

    source: str = "result_positive"

    def holds(self, form: Form, values: Mapping[str, int], result: int) -> bool:
        return result >= 0


@dataclass(frozen=True)
class CarryRule:
    """`no_carry` / `requires_carry`, column by column.

    Separates the page that introduces carrying from the ones before it.
    """

    source: str
    required: bool

    def holds(self, form: Form, values: Mapping[str, int], result: int) -> bool:
        return _has_carry(values["a"], values["b"]) == self.required


@dataclass(frozen=True)
class BorrowRule:
    """`no_borrow` / `requires_borrow`. The same idea, for subtraction."""

    source: str
    required: bool

    def holds(self, form: Form, values: Mapping[str, int], result: int) -> bool:
        return _has_borrow(values["a"], values["b"]) == self.required


@dataclass(frozen=True)
class DividesEvenly:
    """Division before remainders are introduced."""

    source: str = "divides_evenly"

    def holds(self, form: Form, values: Mapping[str, int], result: int) -> bool:
        return values["b"] != 0 and values["a"] % values["b"] == 0


@dataclass(frozen=True)
class ExcludeTrivial:
    """Drops +0, ×1, ×0 and their kin — unless the page is teaching them.

    What counts as trivial depends on the operation: adding zero teaches
    nothing, multiplying by zero teaches nothing, but subtracting zero and
    dividing by one are the same idea for their own operations.
    """

    source: str = "exclude_trivial"

    def holds(self, form: Form, values: Mapping[str, int], result: int) -> bool:
        a, b = values["a"], values["b"]
        if form.symbol == "+":
            return a != 0 and b != 0
        if form.symbol == "-":
            return b != 0
        if form.symbol == TIMES:
            return a not in (0, 1) and b not in (0, 1)
        if form.symbol == DIVIDE:
            return a != 0 and b != 1
        return True


# --------------------------------------------------------------------------
# Page constraints
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class MinDistinctOperands:
    """`min_distinct_operands: 8`.

    Stops a page collapsing into near-identical problems. A page of 1+1, 2+1,
    3+1 satisfies every range and teaches nothing.
    """

    source: str
    minimum: int

    def holds(self, page: Sequence[Mapping[str, int]]) -> bool:
        seen: set[int] = set()
        for values in page:
            seen.update(values.values())
        return len(seen) >= self.minimum


@dataclass(frozen=True)
class MixedOperandOrder:
    """`mixed_operand_order: 6` — at least this many problems each way.

    Not in the original constraint table. Added for the late bands of a level,
    where the curriculum document asks for the same facts "with the addend order
    varied": a child who has only ever seen 3 + 6 should also meet 6 + 3 and
    recognise it as the same fact rather than a new one.
    """

    source: str
    minimum: int

    def holds(self, page: Sequence[Mapping[str, int]]) -> bool:
        ascending = sum(1 for v in page if v["a"] < v["b"])
        descending = sum(1 for v in page if v["a"] > v["b"])
        return ascending >= self.minimum and descending >= self.minimum


# --------------------------------------------------------------------------
# Parsing
# --------------------------------------------------------------------------

_BOUND = re.compile(r"^(sum|product|result)\s*(<=|>=|<|>|==)\s*(-?\d+)$")
_PARAMETERISED = re.compile(r"^(min_distinct_operands|mixed_operand_order)\s*:\s*(\d+)$")

_BARE_PROBLEM: dict[str, object] = {
    "result_positive": ResultPositive(),
    "divides_evenly": DividesEvenly(),
    "exclude_trivial": ExcludeTrivial(),
    "no_carry": CarryRule("no_carry", required=False),
    "requires_carry": CarryRule("requires_carry", required=True),
    "no_borrow": BorrowRule("no_borrow", required=False),
    "requires_borrow": BorrowRule("requires_borrow", required=True),
}


def parse(source: str) -> ProblemConstraint | PageConstraint:
    text = source.strip()

    bare = _BARE_PROBLEM.get(text)
    if bare is not None:
        return bare  # type: ignore[return-value]

    bound = _BOUND.match(text)
    if bound:
        _, operator, value = bound.groups()
        return ResultBound(text, operator, int(value))

    parameterised = _PARAMETERISED.match(text)
    if parameterised:
        name, value = parameterised.groups()
        if name == "min_distinct_operands":
            return MinDistinctOperands(text, int(value))
        return MixedOperandOrder(text, int(value))

    known = ", ".join(sorted(_BARE_PROBLEM))
    raise ValueError(
        f"unknown constraint {source!r}. Known bare constraints: {known}. "
        "Also 'sum|product|result <op> n', 'min_distinct_operands: n', "
        "'mixed_operand_order: n'."
    )


def split(sources: Sequence[str]) -> tuple[list[ProblemConstraint], list[PageConstraint]]:
    """Parse and sort into the two kinds."""
    problem: list[ProblemConstraint] = []
    page: list[PageConstraint] = []
    for source in sources:
        constraint = parse(source)
        if isinstance(constraint, (MinDistinctOperands, MixedOperandOrder)):
            page.append(constraint)
        else:
            problem.append(constraint)  # type: ignore[arg-type]
    return problem, page


# --------------------------------------------------------------------------
# Digit mechanics
# --------------------------------------------------------------------------


def _has_carry(a: int, b: int) -> bool:
    """True if adding these column by column carries anywhere."""
    a, b = abs(a), abs(b)
    carry = 0
    while a or b:
        column = (a % 10) + (b % 10) + carry
        carry = 1 if column >= 10 else 0
        if carry:
            return True
        a //= 10
        b //= 10
    return False


def _has_borrow(a: int, b: int) -> bool:
    """True if subtracting these column by column borrows anywhere."""
    if b > a:
        return True
    borrow = 0
    while b or borrow:
        column = (a % 10) - (b % 10) - borrow
        if column < 0:
            return True
        borrow = 0
        a //= 10
        b //= 10
    return False
