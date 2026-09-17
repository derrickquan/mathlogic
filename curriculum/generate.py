"""Page generation.

Deterministic throughout: the same template produces the same pages forever.
That is not a nicety. Pages are frozen once published because a student
repeating a packet must meet the same problems and get faster, and the seed is
stored so a page can be regenerated and checked against what was published.

Each page draws from its own stream, derived from the band's seed and the page
number, so page 137 regenerates without replaying the 136 before it.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Sequence

from .rng import Rng, derive
from .template import Band, Level

# How many times a page may be redrawn before we give up. Page constraints are
# cheap to satisfy when the pool is healthy; needing hundreds of attempts means
# the band is misconfigured, and a loud failure beats a slow one.
MAX_DRAWS = 200


@dataclass(frozen=True)
class Problem:
    position: int
    prompt: str
    correct_answer: str
    answer_shape: str
    operands: Mapping[str, int]


@dataclass(frozen=True)
class Page:
    page_number: int
    band: Band
    problems: tuple[Problem, ...]


def candidate_pool(band: Band) -> list[dict[str, int]]:
    """Every operand combination the band's problem constraints allow.

    Built once per band and iterated in a fixed order, so the pool a page draws
    from is identical on every run.
    """
    form = band.form
    axes = [(name, band.operand_values(name)) for name in form.operands]

    pool: list[dict[str, int]] = []
    for combination in _product(axes):
        result = form.evaluate(combination)
        if result is None:
            continue
        if all(c.holds(form, combination, result) for c in band.problem_constraints):
            pool.append(combination)
    return pool


def _product(axes: Sequence[tuple[str, Sequence[int]]]) -> list[dict[str, int]]:
    combinations: list[dict[str, int]] = [{}]
    for name, values in axes:
        combinations = [{**base, name: value} for base in combinations for value in values]
    return combinations


def generate_page(band: Band, page_number: int) -> Page:
    if not band.covers(page_number):
        raise ValueError(f"page {page_number} is outside band {band.page_from}..{band.page_to}")

    form = band.form
    wanted = band.problems_per_page
    pool = candidate_pool(band)

    if not pool:
        raise ValueError(
            f"band {band.page_from}..{band.page_to} has no problems at all: "
            f"the operand ranges and constraints {list(band.constraint_sources)} "
            "exclude every combination"
        )
    if band.no_repeat_within_page and len(pool) < wanted:
        raise ValueError(
            f"band {band.page_from}..{band.page_to} needs {wanted} distinct problems per page "
            f"but its operand ranges and constraints allow only {len(pool)}. "
            "Widen the ranges, relax a constraint, or lower problems_per_page."
        )

    rng = Rng(derive(band.seed, page_number))

    for _ in range(MAX_DRAWS):
        if band.no_repeat_within_page:
            draw = rng.shuffled(pool)[:wanted]
        else:
            draw = [pool[rng.below(len(pool))] for _ in range(wanted)]
        if all(constraint.holds(draw) for constraint in band.page_constraints):
            break
    else:
        unmet = [
            constraint.source
            for constraint in band.page_constraints
            if not constraint.holds(draw)
        ]
        raise ValueError(
            f"page {page_number}: gave up after {MAX_DRAWS} draws trying to satisfy "
            f"{unmet} from a pool of {len(pool)} problems. The constraint is probably "
            "impossible for this pool rather than merely unlucky."
        )

    problems = tuple(
        Problem(
            position=position,
            prompt=form.render(values),
            correct_answer=str(form.evaluate(values)),
            answer_shape=form.answer_shape,
            operands=dict(values),
        )
        for position, values in enumerate(draw, start=1)
    )
    return Page(page_number=page_number, band=band, problems=problems)


def generate_level(level: Level) -> list[Page]:
    return [
        generate_page(level.band_for(page_number), page_number)
        for page_number in range(1, level.page_count + 1)
    ]
