"""The values the progression rules move between.

Everything here is frozen. A decision produces a new position and a list of
events rather than mutating anything, so the rules can be tested without a
database and so the events that explain a change are produced at the same moment
as the change itself — not reconstructed afterwards from what the row now says.

The enum values match the PostgreSQL enums in `docs/schema.sql` exactly. If one
side gains a member, the other has to.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class Location(str, Enum):
    """Where a packet was worked. Only the centre drives packet resizing."""

    CENTRE = "centre"
    HOME = "home"


class EventKind(str, Enum):
    """Matches `student_event_kind`."""

    ADVANCED = "advanced"
    DEMOTED_FAILURE = "demoted_failure"
    DEMOTED_BACKLOG = "demoted_backlog"
    PACKET_SIZE_UP = "packet_size_up"
    PACKET_SIZE_DOWN = "packet_size_down"
    PLACED = "placed"


class CorrectionStatus(str, Enum):
    """Matches `correction_status`."""

    PENDING = "pending"
    RESOLVED = "resolved"
    SKIPPED = "skipped"
    CANCELLED = "cancelled"


@dataclass(frozen=True)
class Position:
    """Where a student is: the next page they will be given, and how big their
    packets are.

    Packet size belongs here rather than to the level. It tracks the student's
    speed, so two children on the same page can be on different sizes.
    """

    level: str
    page: int
    packet_size: int

    def __post_init__(self) -> None:
        if self.page < 1:
            raise ValueError(f"page must be at least 1, got {self.page}")
        if self.packet_size not in (5, 10):
            raise ValueError(f"packet_size must be 5 or 10, got {self.packet_size}")


@dataclass(frozen=True)
class Packet:
    """A runtime assignment, not a row of the curriculum.

    `problem_count` is captured here at assignment time so the gate does not have
    to recount later, and stays right even if the page numbering around it moves.
    """

    level: str
    start_page: int
    page_count: int
    problem_count: int
    intended_for: Location

    @property
    def end_page(self) -> int:
        return self.start_page + self.page_count - 1


@dataclass(frozen=True)
class AttemptResult:
    """A graded attempt at a packet. Attempts are append-only, so this describes
    one row and never replaces an earlier one."""

    packet: Packet
    attempt_number: int
    location: Location
    wrong_count: int
    active_seconds: int

    def __post_init__(self) -> None:
        if self.attempt_number < 1:
            raise ValueError(f"attempt_number must be at least 1, got {self.attempt_number}")
        if self.wrong_count < 0:
            raise ValueError(f"wrong_count cannot be negative, got {self.wrong_count}")

    @property
    def minutes_per_page(self) -> float:
        if self.packet.page_count <= 0:
            raise ValueError("a packet with no pages has no pace")
        return self.active_seconds / self.packet.page_count / 60


@dataclass(frozen=True)
class Event:
    """Something that happened to a student's placement.

    Both demotion paths write one, so repeated drops are visible as a pattern
    rather than as isolated incidents.
    """

    kind: EventKind
    from_position: Position | None = None
    to_position: Position | None = None
    note: str = ""


@dataclass(frozen=True)
class Outcome:
    """What follows from a graded attempt."""

    position: Position
    events: tuple[Event, ...] = field(default_factory=tuple)
    repeat: bool = False
    flag_facilitator: bool = False
    escalate_to_parents: bool = False
    note: str = ""

    @property
    def passed(self) -> bool:
        return not self.repeat and not any(
            e.kind in (EventKind.DEMOTED_FAILURE, EventKind.DEMOTED_BACKLOG) for e in self.events
        )
