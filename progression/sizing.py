"""The packet sizing rule.

A student on 10-page packets who consistently exceeds 45 minutes drops to 5. A
student on 5-page packets who consistently finishes under 20 minutes returns to
10. Both thresholds are expressed per page — 4.5 and 4.0 minutes — because that
is what makes them comparable across sizes and what creates the dead band
between them. A student sitting at 4.2 minutes a page does not oscillate week to
week whichever size they are on.

Three conditions hold it steady:

  * **Accumulated active time, not wall clock.** A 10-page packet that exceeds 45
    minutes spans more than one session by definition, so the measure has to add
    up across them. Active time is pen-down time plus gaps under about 90
    seconds, which keeps a bathroom break out of the number.
  * **In-centre packets only.** Homework conditions are uncontrolled — dinner, a
    sibling, a child wandering off mid-packet. Home timing is recorded and shown
    to parents but never resizes anything.
  * **Three consecutive packets.** Two reacts to a bad day; four is too slow to
    be any help.
"""

from __future__ import annotations

from typing import Sequence

from .models import AttemptResult, Event, EventKind, Location, Position

#: Minutes per page. A 10-page packet over 45 minutes; a 5-page packet under 20.
TOO_SLOW = 4.5
FAST_ENOUGH = 4.0

#: "Consistently" means this many consecutive in-centre packets.
CONSECUTIVE = 3


def resize(position: Position, history: Sequence[AttemptResult]) -> tuple[Position, tuple[Event, ...]]:
    """The student's position with packet size adjusted, and the event if it moved.

    `history` is their graded attempts, newest last. Home attempts and anything
    that is not a full packet are ignored rather than filtered by the caller, so
    there is one place where that rule lives.
    """
    recent = [a for a in history if a.location is Location.CENTRE][-CONSECUTIVE:]
    if len(recent) < CONSECUTIVE:
        return position, ()

    rates = [a.minutes_per_page for a in recent]

    if position.packet_size == 10 and all(rate > TOO_SLOW for rate in rates):
        moved = Position(position.level, position.page, 5)
        return moved, (
            Event(
                EventKind.PACKET_SIZE_DOWN,
                from_position=position,
                to_position=moved,
                note=(
                    f"{CONSECUTIVE} in-centre packets over {TOO_SLOW} minutes a page "
                    f"({_summary(rates)}). Ten pages is too long a sitting."
                ),
            ),
        )

    if position.packet_size == 5 and all(rate < FAST_ENOUGH for rate in rates):
        moved = Position(position.level, position.page, 10)
        return moved, (
            Event(
                EventKind.PACKET_SIZE_UP,
                from_position=position,
                to_position=moved,
                note=(
                    f"{CONSECUTIVE} in-centre packets under {FAST_ENOUGH} minutes a page "
                    f"({_summary(rates)}). Ready for ten again."
                ),
            ),
        )

    return position, ()


def _summary(rates: Sequence[float]) -> str:
    return ", ".join(f"{rate:.1f}" for rate in rates)
