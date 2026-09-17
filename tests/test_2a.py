"""Level 2A itself — the content that goes in front of children.

The test that matters most here is the answer key: a wrong answer marked correct
is the worst bug this system can have, because the child is told they are wrong
when they are right, and the parent is told so too.
"""

from __future__ import annotations

import json

import pytest

from curriculum import GOLDEN_DIR, digest, generate_level, load_level

PROBLEMS_PER_PAGE = 20


@pytest.fixture(scope="module")
def level():
    return load_level("2A")


@pytest.fixture(scope="module")
def pages(level):
    return generate_level(level)


def test_the_level_is_two_hundred_pages_of_twenty(level, pages):
    assert len(pages) == level.page_count == 200
    assert all(len(page.problems) == PROBLEMS_PER_PAGE for page in pages)
    assert sum(len(page.problems) for page in pages) == 4000


def test_every_answer_key_is_correct(pages):
    for page in pages:
        for problem in page.problems:
            a, b = problem.operands["a"], problem.operands["b"]
            assert problem.prompt == f"{a} + {b}"
            assert problem.correct_answer == str(a + b), (
                f"page {page.page_number} position {problem.position}: "
                f"{problem.prompt} keyed as {problem.correct_answer}"
            )


def test_nothing_exceeds_the_level(pages):
    """Addition within 10. A sum of 11 is silently teaching level A."""
    for page in pages:
        for problem in page.problems:
            assert int(problem.correct_answer) <= 10, (
                f"page {page.page_number}: {problem.prompt} leaves the level"
            )


def test_no_trivial_problems(pages):
    for page in pages:
        for problem in page.problems:
            assert problem.operands["a"] >= 1 and problem.operands["b"] >= 1


def test_answers_run_from_two_to_ten(pages):
    for page in pages:
        for problem in page.problems:
            assert 2 <= int(problem.correct_answer) <= 10


def test_the_answer_ten_is_common_and_is_two_digits(pages):
    """A v1 assumption that does not survive contact with the level.

    `curriculum-templates.md` picked 2A partly because "answers are single
    digits". Addition within 10 cannot be that: there are nine ways to make 10
    and one way to make 2, so 10 is the single most common answer in the level.
    The tablet answer box and the recogniser must handle two digits from day one.

    This test exists to stop anyone quietly reintroducing the single-digit
    assumption.
    """
    answers = [p.correct_answer for page in pages for p in page.problems]
    tens = [a for a in answers if a == "10"]
    assert len(tens) > len(answers) // 10, "10 is a substantial share of the level"
    assert all(
        any(p.correct_answer == "10" for p in page.problems) for page in pages
    ), "every page contains at least one two-digit answer"


def test_no_page_repeats_a_problem(pages):
    for page in pages:
        prompts = [p.prompt for p in page.problems]
        assert len(set(prompts)) == len(prompts), f"page {page.page_number} repeats a problem"


def test_no_page_collapses_into_near_identical_problems(pages):
    for page in pages:
        operands = {v for p in page.problems for v in p.operands.values()}
        assert len(operands) >= 8, f"page {page.page_number} uses only {len(operands)} values"


def test_early_pages_use_small_second_addends(pages):
    for page in pages[:40]:
        assert all(p.operands["b"] <= 3 for p in page.problems)


def test_late_pages_vary_the_addend_order(pages):
    for page in pages[120:]:
        ascending = sum(1 for p in page.problems if p.operands["a"] < p.operands["b"])
        descending = sum(1 for p in page.problems if p.operands["a"] > p.operands["b"])
        assert ascending >= 6 and descending >= 6, f"page {page.page_number} is one-sided"


def test_the_last_band_drills_the_harder_facts(pages):
    for page in pages[160:]:
        assert all(int(p.correct_answer) >= 5 for p in page.problems)


def test_consecutive_pages_are_not_identical(pages):
    for earlier, later in zip(pages, pages[1:]):
        assert [p.prompt for p in earlier.problems] != [p.prompt for p in later.problems], (
            f"pages {earlier.page_number} and {later.page_number} are the same page"
        )


def test_regenerating_reproduces_the_level_exactly(level):
    """The freeze invariant, at the generator level.

    A student repeating a packet must meet the same problems. That holds only if
    generation is deterministic, so this is the test that protects it.
    """
    assert digest(level, generate_level(level)) == digest(level, generate_level(level))


def test_the_level_has_not_drifted_from_what_was_recorded(level, pages):
    """The freeze invariant, against history.

    If this fails, the content of a level that may already be in front of
    students has changed. Revert the change; do not re-record the digest.
    """
    recorded = json.loads((GOLDEN_DIR / "2A.json").read_text(encoding="utf-8"))
    assert digest(level, pages) == recorded["digest"]
    assert len(pages) == recorded["page_count"]
    assert sum(len(p.problems) for p in pages) == recorded["problem_count"]
