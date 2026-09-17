"""Assembling a packet, and moving one forward or back.

A packet is computed from where the student is and how big their packets are. It
is never stored in the curriculum, because packet size belongs to the student.

Packets do not straddle levels. A packet that would run past the last page of a
level is clipped at the boundary, so the final packet of a level can be shorter
than the student's packet size. The gate is measured per hundred problems, so a
short packet is not a harsher one.
"""

from __future__ import annotations

from .catalogue import Catalogue
from .models import Location, Packet, Position


def assemble(position: Position, catalogue: Catalogue, intended_for: Location) -> Packet:
    info = catalogue.info(position.level)
    if position.page > info.page_count:
        raise ValueError(
            f"page {position.page} is past the end of level {position.level}, "
            f"which has {info.page_count} pages"
        )

    page_count = min(position.packet_size, info.page_count - position.page + 1)
    return Packet(
        level=position.level,
        start_page=position.page,
        page_count=page_count,
        problem_count=catalogue.problem_count(position.level, position.page, page_count),
        intended_for=intended_for,
    )


def advance(position: Position, catalogue: Catalogue) -> Position | None:
    """The position after a passed packet, or None at the end of the curriculum.

    None means the student has finished everything authored. That is a real
    state, not an error: it is what happens when a fast child reaches the end of
    the levels that exist, and it needs a person, not a rule.
    """
    info = catalogue.info(position.level)
    next_page = position.page + min(position.packet_size, info.page_count - position.page + 1)

    if next_page <= info.page_count:
        return Position(position.level, next_page, position.packet_size)

    following = catalogue.next_level(position.level)
    if following is None:
        return None
    return Position(following.name, 1, position.packet_size)


def go_back(position: Position, catalogue: Catalogue) -> Position:
    """The position one packet back.

    At the first packet of the first level there is nowhere to go, so the student
    stays put. A child failing the very first pages twice does not need to be
    moved; they need someone to sit with them, which is what the flag is for.
    """
    previous_page = position.page - position.packet_size

    if previous_page >= 1:
        return Position(position.level, previous_page, position.packet_size)

    earlier = catalogue.previous_level(position.level)
    if earlier is None:
        return Position(position.level, 1, position.packet_size)

    # Land on the last whole packet of the earlier level, not partway into one.
    whole_packets = max(0, (earlier.page_count - 1) // position.packet_size)
    return Position(earlier.name, whole_packets * position.packet_size + 1, position.packet_size)
