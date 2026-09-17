"""Level and band configuration — the input the generator consumes.

One template per page range within a level, so difficulty ramps across the 200
pages rather than sitting flat. The bands of a level must tile its pages exactly:
the schema's EXCLUDE constraint on `page_templates` stops two bands overlapping,
but nothing in the database notices a gap, and a gap means a page number with no
way to generate it.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping, Sequence

from . import constraints as constraint_module
from .constraints import PageConstraint, ProblemConstraint
from .forms import Form, form_for

# bigint, because that is the column the seed is stored in.
_MAX_SEED = (1 << 63) - 1


@dataclass(frozen=True)
class Band:
    """One `page_templates` row: how to generate pages `page_from`..`page_to`."""

    page_from: int
    page_to: int
    problems_per_page: int
    form_spec: str
    operands: Mapping[str, Mapping[str, Any]]
    constraint_sources: tuple[str, ...]
    no_repeat_within_page: bool
    seed: int

    problem_constraints: tuple[ProblemConstraint, ...] = field(compare=False, repr=False, default=())
    page_constraints: tuple[PageConstraint, ...] = field(compare=False, repr=False, default=())

    @property
    def form(self) -> Form:
        return form_for(self.form_spec)

    def covers(self, page_number: int) -> bool:
        return self.page_from <= page_number <= self.page_to

    def operand_values(self, name: str) -> list[int]:
        spec = self.operands[name]
        if "range" in spec:
            low, high = spec["range"]
            if low > high:
                raise ValueError(f"operand {name!r} has an inverted range {low}..{high}")
            return list(range(int(low), int(high) + 1))
        if "values" in spec:
            return [int(v) for v in spec["values"]]
        raise ValueError(f"operand {name!r} needs either 'range' or 'values'")


@dataclass(frozen=True)
class Level:
    name: str
    sort_order: int
    description: str
    page_count: int
    default_packet_size: int
    bands: tuple[Band, ...]

    def band_for(self, page_number: int) -> Band:
        for band in self.bands:
            if band.covers(page_number):
                return band
        raise ValueError(f"level {self.name} has no band covering page {page_number}")


def load(path: str | Path) -> Level:
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    return build(raw)


def build(raw: Mapping[str, Any]) -> Level:
    bands = tuple(_build_band(entry) for entry in raw["bands"])
    level = Level(
        name=str(raw["level"]),
        sort_order=int(raw["sort_order"]),
        description=str(raw.get("description", "")),
        page_count=int(raw["page_count"]),
        default_packet_size=int(raw.get("default_packet_size", 10)),
        bands=bands,
    )
    _validate(level)
    return level


def _build_band(raw: Mapping[str, Any]) -> Band:
    page_from, page_to = raw["pages"]
    sources = tuple(str(c) for c in raw.get("constraints", []))
    problem_constraints, page_constraints = constraint_module.split(sources)
    return Band(
        page_from=int(page_from),
        page_to=int(page_to),
        problems_per_page=int(raw["problems_per_page"]),
        form_spec=str(raw["form"]),
        operands=dict(raw["operands"]),
        constraint_sources=sources,
        no_repeat_within_page=bool(raw.get("no_repeat_within_page", True)),
        seed=int(raw["seed"]),
        problem_constraints=tuple(problem_constraints),
        page_constraints=tuple(page_constraints),
    )


def _validate(level: Level) -> None:
    if level.page_count < 1:
        raise ValueError(f"level {level.name} has page_count {level.page_count}")
    if level.default_packet_size not in (5, 10):
        raise ValueError(
            f"level {level.name} has default_packet_size {level.default_packet_size}; "
            "the schema allows 5 or 10"
        )
    if not level.bands:
        raise ValueError(f"level {level.name} has no bands")

    ordered = sorted(level.bands, key=lambda b: b.page_from)
    if list(ordered) != list(level.bands):
        raise ValueError(f"level {level.name}: bands must be listed in page order")

    expected_start = 1
    for band in ordered:
        if band.page_from != expected_start:
            raise ValueError(
                f"level {level.name}: bands must tile the level with no gap or overlap; "
                f"expected a band starting at page {expected_start}, found one starting "
                f"at {band.page_from}"
            )
        if band.page_to < band.page_from:
            raise ValueError(
                f"level {level.name}: band {band.page_from}..{band.page_to} ends before it starts"
            )
        if band.problems_per_page < 1:
            raise ValueError(
                f"level {level.name}, band {band.page_from}..{band.page_to}: "
                f"problems_per_page is {band.problems_per_page}"
            )
        if not 0 <= band.seed <= _MAX_SEED:
            raise ValueError(
                f"level {level.name}, band {band.page_from}..{band.page_to}: "
                f"seed {band.seed} does not fit the bigint column"
            )
        form = band.form
        missing = set(form.operands) - set(band.operands)
        if missing:
            raise ValueError(
                f"level {level.name}, band {band.page_from}..{band.page_to}: "
                f"form {form.spec!r} needs operand(s) {sorted(missing)}"
            )
        expected_start = band.page_to + 1

    last = ordered[-1]
    if last.page_to != level.page_count:
        raise ValueError(
            f"level {level.name}: bands stop at page {last.page_to} but the level has "
            f"{level.page_count} pages"
        )


def band_sources(bands: Sequence[Band]) -> list[dict[str, Any]]:
    """The bands as they are written to `page_templates`."""
    return [
        {
            "page_from": band.page_from,
            "page_to": band.page_to,
            "problems_per_page": band.problems_per_page,
            "form": band.form_spec,
            "operands": dict(band.operands),
            "constraints": list(band.constraint_sources),
            "seed": band.seed,
        }
        for band in bands
    ]
