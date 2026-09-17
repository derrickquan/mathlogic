from __future__ import annotations

import pytest

from curriculum import constraints
from curriculum.constraints import _has_borrow, _has_carry
from curriculum.forms import DIVIDE, TIMES, form_for

ADD = form_for("a + b = _")
SUBTRACT = form_for("a - b = _")
MULTIPLY = form_for(f"a {TIMES} b = _")
DIVIDE_FORM = form_for(f"a {DIVIDE} b = _")


def holds(source, form, a, b):
    constraint = constraints.parse(source)
    values = {"a": a, "b": b}
    return constraint.holds(form, values, form.evaluate(values))


def test_sum_bound():
    assert holds("sum <= 10", ADD, 7, 3)
    assert not holds("sum <= 10", ADD, 7, 4)


def test_sum_lower_bound():
    assert holds("sum >= 5", ADD, 2, 3)
    assert not holds("sum >= 5", ADD, 2, 2)


def test_result_positive_allows_zero_but_not_negatives():
    assert holds("result_positive", SUBTRACT, 5, 5)
    assert not holds("result_positive", SUBTRACT, 4, 9)


def test_exclude_trivial_is_per_operation():
    assert not holds("exclude_trivial", ADD, 7, 0)
    assert holds("exclude_trivial", ADD, 7, 1)

    assert not holds("exclude_trivial", MULTIPLY, 7, 1)
    assert not holds("exclude_trivial", MULTIPLY, 0, 5)
    assert holds("exclude_trivial", MULTIPLY, 3, 4)

    assert not holds("exclude_trivial", DIVIDE_FORM, 8, 1)
    assert holds("exclude_trivial", DIVIDE_FORM, 8, 2)


def test_divides_evenly():
    assert holds("divides_evenly", DIVIDE_FORM, 12, 4)
    values = {"a": 13, "b": 4}
    assert DIVIDE_FORM.evaluate(values) is None, "13 ÷ 4 has no integer answer"


@pytest.mark.parametrize(
    "a, b, carries",
    [(7, 2, False), (7, 5, True), (23, 45, False), (28, 45, True), (99, 1, True)],
)
def test_carry_detection(a, b, carries):
    assert _has_carry(a, b) is carries


@pytest.mark.parametrize(
    "a, b, borrows",
    [(9, 4, False), (52, 7, True), (45, 23, False), (43, 28, True), (10, 1, True)],
)
def test_borrow_detection(a, b, borrows):
    assert _has_borrow(a, b) is borrows


def test_carry_rules_are_opposites():
    assert holds("no_carry", ADD, 23, 45)
    assert not holds("requires_carry", ADD, 23, 45)
    assert holds("requires_carry", ADD, 28, 45)


def test_min_distinct_operands():
    constraint = constraints.parse("min_distinct_operands: 4")
    flat = [{"a": 1, "b": 1}, {"a": 2, "b": 1}, {"a": 3, "b": 1}]
    assert not constraint.holds(flat)
    varied = flat + [{"a": 7, "b": 2}]
    assert constraint.holds(varied)


def test_mixed_operand_order():
    constraint = constraints.parse("mixed_operand_order: 2")
    one_way = [{"a": 1, "b": 5}, {"a": 2, "b": 6}, {"a": 3, "b": 7}]
    assert not constraint.holds(one_way)
    both_ways = one_way + [{"a": 8, "b": 1}, {"a": 9, "b": 1}]
    assert constraint.holds(both_ways)


def test_split_sorts_by_kind():
    problem, page = constraints.split(["sum <= 10", "min_distinct_operands: 8", "no_carry"])
    assert len(problem) == 2
    assert len(page) == 1


def test_unknown_constraint_says_what_is_known():
    with pytest.raises(ValueError, match="unknown constraint"):
        constraints.parse("sum_is_lucky")
