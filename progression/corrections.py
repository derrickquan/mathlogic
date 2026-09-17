"""The corrections queue.

Corrections belong to the student, not to an attempt. They survive across days,
they accumulate, and they are cleared at the start of the next in-centre session
before any new material.

    pending ──resolved──▶ resolved        student corrects it
       │
       └──skipped──▶ skipped ──resolved──▶ resolved    fixed in centre later
                        │
                        └──cancelled──▶ cancelled      facilitator clears backlog

Skipping is allowed and visible: a child can close homework with corrections
outstanding, the skip is logged, and it appears in that night's email. Nothing
disappears quietly and no child is trapped at bedtime.

Cancelling is not an administrative tidy-up. A facilitator clearing a backlog is
saying the student was not ready for the material, so it drops them back a
packet. That is the second demotion path, and it writes to the same event history
as the first so repeated drops read as one pattern.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date
from typing import Iterable, Sequence

from .catalogue import Catalogue
from .models import CorrectionStatus, Event, EventKind, Outcome, Position
from .packets import go_back

_ALLOWED: dict[CorrectionStatus, frozenset[CorrectionStatus]] = {
    CorrectionStatus.PENDING: frozenset({CorrectionStatus.RESOLVED, CorrectionStatus.SKIPPED}),
    CorrectionStatus.SKIPPED: frozenset({CorrectionStatus.RESOLVED, CorrectionStatus.CANCELLED}),
    CorrectionStatus.RESOLVED: frozenset(),
    CorrectionStatus.CANCELLED: frozenset(),
}

#: Three nights of skipping means the level is too hard or the child has
#: disengaged. Either way the facilitator should know before the backlog forces
#: the issue, so this is surfaced separately from any score.
SKIP_RUN_TO_FLAG = 3


@dataclass(frozen=True)
class Correction:
    answer_id: str
    status: CorrectionStatus = CorrectionStatus.PENDING
    created_on: date | None = None
    skipped_on: date | None = None

    @property
    def open(self) -> bool:
        return self.status in (CorrectionStatus.PENDING, CorrectionStatus.SKIPPED)


def transition(correction: Correction, to: CorrectionStatus, *, on: date | None = None) -> Correction:
    """Move one correction, refusing anything the state machine does not allow."""
    if to not in _ALLOWED[correction.status]:
        allowed = ", ".join(sorted(s.value for s in _ALLOWED[correction.status])) or "nothing"
        raise ValueError(
            f"a {correction.status.value} correction cannot become {to.value}; "
            f"it can only become {allowed}"
        )
    if to is CorrectionStatus.SKIPPED:
        return replace(correction, status=to, skipped_on=on or date.today())
    return replace(correction, status=to)


def open_queue(corrections: Iterable[Correction]) -> list[Correction]:
    return [c for c in corrections if c.open]


def close_homework(
    corrections: Sequence[Correction], *, on: date | None = None
) -> tuple[list[Correction], int]:
    """The child closes for the night with work outstanding.

    Returns the queue and how many were skipped, which is what the night's email
    reports. Skipping is a legitimate ending, not a failure.
    """
    when = on or date.today()
    out: list[Correction] = []
    skipped = 0
    for correction in corrections:
        if correction.status is CorrectionStatus.PENDING:
            out.append(transition(correction, CorrectionStatus.SKIPPED, on=when))
            skipped += 1
        else:
            out.append(correction)
    return out, skipped


def cancel_backlog(
    position: Position,
    corrections: Sequence[Correction],
    catalogue: Catalogue,
    *,
    staff_name: str = "",
) -> tuple[list[Correction], Outcome]:
    """A facilitator clears the whole backlog, which drops the student a packet.

    This is the second demotion path. It is deliberately not a free action: if
    the corrections have piled up beyond catching up on, the material was too
    hard, and the honest response is to move the child back rather than to make
    the queue disappear.
    """
    outstanding = open_queue(corrections)
    if not outstanding:
        raise ValueError("there is no backlog to cancel")

    cleared = [
        transition(c, CorrectionStatus.CANCELLED) if c.open else c for c in corrections
    ]

    dropped = go_back(position, catalogue)
    by = f" by {staff_name}" if staff_name else ""
    note = (
        f"Backlog of {len(outstanding)} corrections cleared{by}. A backlog that size means "
        "the material was too hard, so the student moves back a packet."
    )

    return cleared, Outcome(
        position=dropped,
        events=(
            Event(
                EventKind.DEMOTED_BACKLOG,
                from_position=position,
                to_position=dropped,
                note=note,
            ),
        ),
        flag_facilitator=True,
        note=note,
    )


def consecutive_skip_nights(corrections: Iterable[Correction]) -> int:
    """How many nights in a row ended with something skipped.

    Worth surfacing on its own, separately from any score: three nights running
    says either the level is too hard or the child has stopped engaging, and both
    want a person before the backlog forces the issue.
    """
    nights = sorted({c.skipped_on for c in corrections if c.skipped_on is not None}, reverse=True)
    if not nights:
        return 0

    run = 1
    for earlier, later in zip(nights[1:], nights):
        if (later - earlier).days == 1:
            run += 1
        else:
            break
    return run


def should_flag_skipping(corrections: Iterable[Correction]) -> bool:
    return consecutive_skip_nights(corrections) >= SKIP_RUN_TO_FLAG
