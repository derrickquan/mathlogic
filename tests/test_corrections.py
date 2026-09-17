from __future__ import annotations

from datetime import date, timedelta

import pytest

from progression import (
    Correction,
    CorrectionStatus,
    EventKind,
    LevelInfo,
    Position,
    StaticCatalogue,
    cancel_backlog,
    close_homework,
    consecutive_skip_nights,
    open_queue,
    should_flag_skipping,
    transition,
)

CATALOGUE = StaticCatalogue([
    LevelInfo("3A", sort_order=5, page_count=200, problems_per_page=20),
    LevelInfo("2A", sort_order=6, page_count=200, problems_per_page=20),
])

TODAY = date(2026, 9, 17)


def pending(n=1):
    return [Correction(answer_id=f"a{i}", created_on=TODAY) for i in range(n)]


def test_a_student_corrects_it():
    c = transition(pending(1)[0], CorrectionStatus.RESOLVED)
    assert c.status is CorrectionStatus.RESOLVED
    assert not c.open


def test_skipping_records_the_night_it_happened():
    c = transition(pending(1)[0], CorrectionStatus.SKIPPED, on=TODAY)
    assert c.status is CorrectionStatus.SKIPPED
    assert c.skipped_on == TODAY
    assert c.open, "a skip does not close anything"


def test_a_skipped_correction_can_still_be_put_right_in_centre():
    c = transition(pending(1)[0], CorrectionStatus.SKIPPED, on=TODAY)
    assert transition(c, CorrectionStatus.RESOLVED).status is CorrectionStatus.RESOLVED


def test_a_resolved_correction_is_finished():
    c = transition(pending(1)[0], CorrectionStatus.RESOLVED)
    with pytest.raises(ValueError, match="cannot become"):
        transition(c, CorrectionStatus.SKIPPED)


def test_a_pending_correction_cannot_be_cancelled_straight_out():
    """Cancelling is a facilitator clearing a backlog, which is a skipped pile."""
    with pytest.raises(ValueError, match="cannot become cancelled"):
        transition(pending(1)[0], CorrectionStatus.CANCELLED)


def test_closing_homework_skips_what_is_left_and_says_how_many():
    queue, skipped = close_homework(pending(3), on=TODAY)
    assert skipped == 3
    assert all(c.status is CorrectionStatus.SKIPPED for c in queue)
    assert len(open_queue(queue)) == 3, "they are waiting for tomorrow, not gone"


def test_closing_homework_with_nothing_outstanding_is_quiet():
    queue, skipped = close_homework([], on=TODAY)
    assert queue == [] and skipped == 0


def test_clearing_a_backlog_drops_the_student_back_a_packet():
    queue, _ = close_homework(pending(14), on=TODAY)
    cleared, outcome = cancel_backlog(Position("2A", 41, 10), queue, CATALOGUE, staff_name="Priya")

    assert all(c.status is CorrectionStatus.CANCELLED for c in cleared)
    assert open_queue(cleared) == []
    assert outcome.position == Position("2A", 31, 10)
    assert [e.kind for e in outcome.events] == [EventKind.DEMOTED_BACKLOG]
    assert outcome.flag_facilitator


def test_both_demotion_paths_write_to_the_same_history():
    """Repeated drops have to read as one pattern, whichever way they happened."""
    from progression import AttemptResult, Location, Packet, decide

    queue, _ = close_homework(pending(9), on=TODAY)
    _, backlog = cancel_backlog(Position("2A", 41, 10), queue, CATALOGUE)

    failed = decide(
        Position("2A", 41, 10),
        AttemptResult(
            packet=Packet("2A", 41, 10, 200, Location.CENTRE),
            attempt_number=2,
            location=Location.CENTRE,
            wrong_count=50,
            active_seconds=1800,
        ),
        CATALOGUE,
    )

    kinds = {backlog.events[0].kind, failed.events[0].kind}
    assert kinds == {EventKind.DEMOTED_BACKLOG, EventKind.DEMOTED_FAILURE}
    assert all(e.from_position and e.to_position for e in backlog.events + failed.events)


def test_cancelling_nothing_is_refused():
    with pytest.raises(ValueError, match="no backlog"):
        cancel_backlog(Position("2A", 41, 10), [], CATALOGUE)


def test_the_cancellation_note_says_why_the_student_moved():
    queue, _ = close_homework(pending(14), on=TODAY)
    _, outcome = cancel_backlog(Position("2A", 41, 10), queue, CATALOGUE, staff_name="Priya")
    note = outcome.events[0].note
    assert "14 corrections" in note and "Priya" in note
    assert "too hard" in note


def test_three_nights_of_skipping_is_flagged_on_its_own():
    nights = [TODAY - timedelta(days=n) for n in (0, 1, 2)]
    queue = [Correction(answer_id=f"a{i}", status=CorrectionStatus.SKIPPED, skipped_on=n)
             for i, n in enumerate(nights)]
    assert consecutive_skip_nights(queue) == 3
    assert should_flag_skipping(queue)


def test_a_broken_run_of_skips_is_not_flagged():
    nights = [TODAY, TODAY - timedelta(days=1), TODAY - timedelta(days=5)]
    queue = [Correction(answer_id=f"a{i}", status=CorrectionStatus.SKIPPED, skipped_on=n)
             for i, n in enumerate(nights)]
    assert consecutive_skip_nights(queue) == 2
    assert not should_flag_skipping(queue)


def test_several_skips_on_one_night_count_as_one_night():
    queue = [Correction(answer_id=f"a{i}", status=CorrectionStatus.SKIPPED, skipped_on=TODAY)
             for i in range(6)]
    assert consecutive_skip_nights(queue) == 1
