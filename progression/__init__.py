"""Progression: where a student is, what they get next, and why they moved.

Pure rules over frozen values. Nothing here touches a database, a clock it was
not given, or an HTTP request, so every decision the system makes about a child
can be tested directly.

    from progression import Position, Location, assemble, decide, from_templates

    catalogue = from_templates()
    where = Position(level="2A", page=41, packet_size=10)
    packet = assemble(where, catalogue, Location.CENTRE)

    outcome = decide(where, graded_attempt, catalogue)
    outcome.position          # where they go next
    outcome.events            # what to write to student_events
    outcome.flag_facilitator  # whether someone should go and teach

The five rules, and where each lives:

    packets.py      a packet is computed from position and packet size
    gate.py         95% per hundred problems; two failures drop a packet
    sizing.py       three in-centre packets either side of a dead band
    corrections.py  a queue belonging to the student, and the second demotion path
    catalogue.py    the little the rules need to know about the curriculum
"""

from __future__ import annotations

from .catalogue import Catalogue, LevelInfo, StaticCatalogue, from_templates
from .corrections import (
    Correction,
    cancel_backlog,
    close_homework,
    consecutive_skip_nights,
    open_queue,
    should_flag_skipping,
    transition,
)
from .gate import allowed_wrong, decide, passed
from .models import (
    AttemptResult,
    CorrectionStatus,
    Event,
    EventKind,
    Location,
    Outcome,
    Packet,
    Position,
)
from .packets import advance, assemble, go_back
from .sizing import resize

__all__ = [
    "AttemptResult",
    "Catalogue",
    "Correction",
    "CorrectionStatus",
    "Event",
    "EventKind",
    "LevelInfo",
    "Location",
    "Outcome",
    "Packet",
    "Position",
    "StaticCatalogue",
    "advance",
    "allowed_wrong",
    "assemble",
    "cancel_backlog",
    "close_homework",
    "consecutive_skip_nights",
    "decide",
    "from_templates",
    "go_back",
    "open_queue",
    "passed",
    "resize",
    "should_flag_skipping",
    "transition",
]
