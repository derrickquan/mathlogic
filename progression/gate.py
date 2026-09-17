"""The advancement gate, and what follows from failing it.

95% accuracy, measured per hundred problems rather than per packet. Packet size
tracks student speed, so a 5-page packet goes to the slowest students rather than
the most advanced; applying 95% to the packet would put the strictest gate on
exactly the children who are struggling.

Failing twice drops the student back a packet. The system decides — the
facilitator is told to go and sit with the child, not asked to rule on it.
Removing that decision is what keeps one person teaching rather than administering.
"""

from __future__ import annotations

import math
from datetime import date, timedelta
from typing import Sequence

from .catalogue import Catalogue
from .models import AttemptResult, Event, EventKind, Outcome, Position
from .packets import advance, go_back

#: Two drops inside this window mean the placement is wrong, not the week.
ESCALATION_WINDOW = timedelta(days=30)
ESCALATION_THRESHOLD = 2


def allowed_wrong(problem_count: int) -> int:
    """Five per cent, rounded up, never below one.

    Rounding up rather than down keeps short packets from becoming the harshest:
    100 problems allow 5, 30 allow 2, 20 allow 1, and 6 still allow 1.
    """
    if problem_count < 1:
        raise ValueError(f"a packet needs at least one problem, got {problem_count}")
    return max(1, math.ceil(problem_count * 0.05))


def passed(attempt: AttemptResult) -> bool:
    return attempt.wrong_count <= allowed_wrong(attempt.packet.problem_count)


def decide(
    position: Position,
    attempt: AttemptResult,
    catalogue: Catalogue,
    *,
    recent_demotions: Sequence[date] = (),
    today: date | None = None,
) -> Outcome:
    """What happens after a packet is graded.

    `recent_demotions` is the dates of this student's previous drops, from either
    path. Repeated demotion is its own signal: one drop is a bad week, two in a
    month means the placement is wrong and needs a parent conversation rather
    than another flag on the console.
    """
    if passed(attempt):
        moved = advance(position, catalogue)
        if moved is None:
            return Outcome(
                position=position,
                flag_facilitator=True,
                note=(
                    "Passed the last packet of the last authored level. There is nothing "
                    "further to assign, which is a placement conversation, not a rule."
                ),
            )
        return Outcome(
            position=moved,
            events=(Event(EventKind.ADVANCED, from_position=position, to_position=moved),),
        )

    if attempt.attempt_number < 2:
        # Same packet, same problems. The point is to get quicker at them.
        return Outcome(position=position, repeat=True)

    dropped = go_back(position, catalogue)
    stuck = dropped == position

    demotions = list(recent_demotions)
    when = today or date.today()
    demotions.append(when)
    escalate = _repeated(demotions, when)

    note = (
        "Failed the same packet twice at the very start of the curriculum, so there is "
        "nowhere to drop to. Go and teach."
        if stuck
        else "Failed the same packet twice. Moved back a packet automatically."
    )

    return Outcome(
        position=dropped,
        events=(
            Event(
                EventKind.DEMOTED_FAILURE,
                from_position=position,
                to_position=dropped,
                note=note,
            ),
        ),
        flag_facilitator=True,
        escalate_to_parents=escalate,
        note=note,
    )


def _repeated(demotions: Sequence[date], today: date) -> bool:
    recent = [d for d in demotions if today - d <= ESCALATION_WINDOW]
    return len(recent) >= ESCALATION_THRESHOLD
