from __future__ import annotations

import pytest

from curriculum import build, generate_page
from curriculum.generate import candidate_pool
from tests.test_template import a_band, a_level


def band_of(**overrides):
    return build(a_level([a_band(1, 100, **overrides)])).bands[0]


def test_pool_respects_problem_constraints():
    pool = candidate_pool(band_of(constraints=["sum <= 10", "exclude_trivial"]))
    assert all(1 <= v["a"] and 1 <= v["b"] and v["a"] + v["b"] <= 10 for v in pool)
    # a,b >= 1 with a+b <= 10 is 1+2+...+9 combinations.
    assert len(pool) == 45


def test_the_same_page_generates_identically_every_time():
    band = band_of()
    first = generate_page(band, 17)
    second = generate_page(band, 17)
    assert [(p.prompt, p.correct_answer) for p in first.problems] == [
        (p.prompt, p.correct_answer) for p in second.problems
    ]


def test_different_pages_differ():
    band = band_of()
    first = [p.prompt for p in generate_page(band, 17).problems]
    second = [p.prompt for p in generate_page(band, 18).problems]
    assert first != second


def test_no_problem_repeats_within_a_page():
    band = band_of()
    prompts = [p.prompt for p in generate_page(band, 5).problems]
    assert len(set(prompts)) == len(prompts)


def test_positions_are_one_based_and_contiguous():
    page = generate_page(band_of(), 5)
    assert [p.position for p in page.problems] == list(range(1, 21))


def test_a_pool_too_small_for_the_page_fails_loudly():
    band = band_of(
        operands={"a": {"range": [1, 3]}, "b": {"range": [1, 2]}},
        constraints=["sum <= 10"],
    )
    with pytest.raises(ValueError, match="allow only 6"):
        generate_page(band, 1)


def test_an_impossible_constraint_set_is_reported_not_retried_forever():
    band = band_of(constraints=["sum <= 10", "sum >= 11"])
    with pytest.raises(ValueError, match="no problems at all"):
        generate_page(band, 1)


def test_an_unsatisfiable_page_constraint_gives_up_with_a_useful_message():
    # Every problem has a < b, so no page can carry six the other way.
    band = band_of(
        operands={"a": {"range": [1, 2]}, "b": {"range": [5, 8]}},
        problems_per_page=8,
        constraints=["sum <= 10", "mixed_operand_order: 6"],
    )
    with pytest.raises(ValueError, match="gave up after"):
        generate_page(band, 1)


def test_page_constraints_are_actually_satisfied():
    band = band_of(constraints=["sum <= 10", "mixed_operand_order: 6"])
    page = generate_page(band, 9)
    ascending = sum(1 for p in page.problems if p.operands["a"] < p.operands["b"])
    descending = sum(1 for p in page.problems if p.operands["a"] > p.operands["b"])
    assert ascending >= 6 and descending >= 6


def test_a_page_outside_its_band_is_refused():
    band = build(a_level([a_band(1, 50), a_band(51, 100)])).bands[0]
    with pytest.raises(ValueError, match="outside band"):
        generate_page(band, 80)
