"""What the progression rules need to know about the curriculum, and no more.

Progression must not import the generator. It needs four facts — how long a level
is, what comes before and after it, and how many problems sit in a run of pages —
and taking them through a small protocol keeps the rules testable against a
made-up three-level curriculum instead of the real one.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, Sequence


@dataclass(frozen=True)
class LevelInfo:
    name: str
    sort_order: int
    page_count: int
    default_packet_size: int = 10
    problems_per_page: int = 20


class Catalogue(Protocol):
    def info(self, level: str) -> LevelInfo: ...
    def next_level(self, level: str) -> LevelInfo | None: ...
    def previous_level(self, level: str) -> LevelInfo | None: ...
    def problem_count(self, level: str, start_page: int, page_count: int) -> int: ...


class StaticCatalogue:
    """A catalogue built from a list of levels.

    Used for the levels that are authored, and for tests that need a curriculum
    with something either side of the level under test.
    """

    def __init__(self, levels: Sequence[LevelInfo]) -> None:
        if not levels:
            raise ValueError("a catalogue needs at least one level")
        self._ordered = tuple(sorted(levels, key=lambda lv: lv.sort_order))
        self._by_name = {lv.name: lv for lv in self._ordered}
        if len(self._by_name) != len(self._ordered):
            raise ValueError("two levels share a name")
        orders = {lv.sort_order for lv in self._ordered}
        if len(orders) != len(self._ordered):
            raise ValueError("two levels share a sort_order")

    def info(self, level: str) -> LevelInfo:
        try:
            return self._by_name[level]
        except KeyError:
            known = ", ".join(self._by_name) or "none"
            raise ValueError(f"unknown level {level!r}; the catalogue holds {known}") from None

    def next_level(self, level: str) -> LevelInfo | None:
        index = self._ordered.index(self.info(level))
        return self._ordered[index + 1] if index + 1 < len(self._ordered) else None

    def previous_level(self, level: str) -> LevelInfo | None:
        index = self._ordered.index(self.info(level))
        return self._ordered[index - 1] if index > 0 else None

    def problem_count(self, level: str, start_page: int, page_count: int) -> int:
        info = self.info(level)
        if start_page < 1 or start_page > info.page_count:
            raise ValueError(f"page {start_page} is outside level {level} (1..{info.page_count})")
        if page_count < 1:
            raise ValueError(f"a packet needs at least one page, got {page_count}")
        if start_page + page_count - 1 > info.page_count:
            raise ValueError(
                f"pages {start_page}..{start_page + page_count - 1} run past the end of "
                f"level {level}, which has {info.page_count}"
            )
        return page_count * info.problems_per_page


def from_templates() -> StaticCatalogue:
    """A catalogue of the levels that are actually authored.

    Reads the generator's own template files, so a level appears here the moment
    it is authored and the two can never disagree about how long it is.
    """
    from curriculum import TEMPLATE_DIR, load

    levels = []
    for path in sorted(TEMPLATE_DIR.glob("*.json")):
        level = load(path)
        per_page = {band.problems_per_page for band in level.bands}
        if len(per_page) != 1:
            raise ValueError(
                f"level {level.name} varies problems per page across its bands "
                f"({sorted(per_page)}). The packet problem count assumes one value per level; "
                "teach the catalogue to sum across bands before authoring such a level."
            )
        levels.append(
            LevelInfo(
                name=level.name,
                sort_order=level.sort_order,
                page_count=level.page_count,
                default_packet_size=level.default_packet_size,
                problems_per_page=per_page.pop(),
            )
        )
    return StaticCatalogue(levels)
