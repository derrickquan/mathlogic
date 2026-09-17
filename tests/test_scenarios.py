"""Whole journeys through the rules, rather than one rule at a time.

The unit tests check each rule in isolation. These check that the rules compose
the way a term actually unfolds — because the interesting failures are in the
seams: a student who is resized in the same week they are demoted, a backlog
cancelled a fortnight after a failure, a child who reaches the end of what has
been authored.
"""

from __future__ import annotations

from datetime import date, timedelta

from progression import (
    AttemptResult,
    Correction,
    CorrectionStatus,
    EventKind,
    LevelInfo,
    Location,
    Packet,
    Position,
    StaticCatalogue,
    assemble,
    cancel_backlog,
    close_homework,
    decide,
    resize,
)

CATALOGUE = StaticCatalogue([
    LevelInfo("3A", sort_order=5, page_count=200, problems_per_page=20),
    LevelInfo("2A", sort_order=6, page_count=200, problems_per_page=20),
    LevelInfo("A", sort_order=7, page_count=200, problems_per_page=20),
])

START = date(2026, 9, 1)


def worked(position, *, wrong, minutes, number=1, location=Location.CENTRE):
    packet = assemble(position, CATALOGUE, location)
    return AttemptResult(
        packet=packet,
        attempt_number=number,
        location=location,
        wrong_count=wrong,
        active_seconds=int(minutes * 60),
    )


def test_a_steady_student_walks_forward_a_packet_at_a_time():
    where = Position("2A", 41, 10)
    history = []

    for _ in range(4):
        attempt = worked(where, wrong=3, minutes=32)
        history.append(attempt)
        outcome = decide(where, attempt, CATALOGUE)
        assert outcome.events[0].kind is EventKind.ADVANCED
        where, _ = resize(outcome.position, history)

    assert where == Position("2A", 81, 10)
    assert where.packet_size == 10, (
        "3.2 minutes a page is quick, but the rule only ever raises 5 to 10 — "
        "there is nothing above 10 to be promoted to"
    )


def test_a_struggling_student_repeats_then_drops_then_is_resized():
    """The sequence the spec describes: two failures move them back, and the
    time those failures took moves them onto shorter packets."""
    where = Position("2A", 41, 10)
    history = []

    first = worked(where, wrong=18, minutes=52, number=1)
    history.append(first)
    outcome = decide(where, first, CATALOGUE)
    assert outcome.repeat and outcome.position == where

    second = worked(where, wrong=15, minutes=55, number=2)
    history.append(second)
    outcome = decide(where, second, CATALOGUE)
    assert outcome.events[0].kind is EventKind.DEMOTED_FAILURE
    assert outcome.flag_facilitator
    where = outcome.position
    assert where == Position("2A", 31, 10)

    third = worked(where, wrong=4, minutes=50)
    history.append(third)
    where, events = resize(where, history)

    assert where == Position("2A", 31, 5), "three slow in-centre packets, ten becomes five"
    assert [e.kind for e in events] == [EventKind.PACKET_SIZE_DOWN]

    packet = assemble(where, CATALOGUE, Location.CENTRE)
    assert packet.page_count == 5 and packet.problem_count == 100
    assert packet.start_page == 31, "resizing does not move them off the page they are on"


def test_a_drop_from_each_path_inside_a_month_reaches_the_parents():
    where = Position("2A", 41, 10)

    queue, _ = close_homework(
        [Correction(answer_id=f"a{i}", created_on=START) for i in range(12)], on=START
    )
    _, backlog = cancel_backlog(where, queue, CATALOGUE, staff_name="Priya")
    assert backlog.events[0].kind is EventKind.DEMOTED_BACKLOG
    where = backlog.position

    later = START + timedelta(days=11)
    failed = decide(
        where,
        worked(where, wrong=40, minutes=48, number=2),
        CATALOGUE,
        recent_demotions=[START],
        today=later,
    )

    assert failed.events[0].kind is EventKind.DEMOTED_FAILURE
    assert failed.escalate_to_parents, (
        "two drops in eleven days is a placement problem, not two bad weeks"
    )


def test_homework_timing_never_shortens_a_packet_however_bad_it_looks():
    where = Position("2A", 41, 10)
    evenings = [
        worked(where, wrong=2, minutes=110, location=Location.HOME),
        worked(where, wrong=1, minutes=95, location=Location.HOME),
        worked(where, wrong=3, minutes=130, location=Location.HOME),
    ]
    resized, events = resize(where, evenings)
    assert resized.packet_size == 10 and events == ()


def test_a_quick_student_on_five_pages_earns_ten_back():
    where = Position("2A", 31, 5)
    history = [worked(where, wrong=1, minutes=18) for _ in range(3)]
    where, events = resize(where, history)
    assert where.packet_size == 10
    assert [e.kind for e in events] == [EventKind.PACKET_SIZE_UP]

    assert assemble(where, CATALOGUE, Location.CENTRE).page_count == 10


def test_a_student_crosses_a_level_boundary_forward_and_back():
    where = Position("2A", 191, 10)

    forward = decide(where, worked(where, wrong=2, minutes=30), CATALOGUE)
    assert forward.position == Position("A", 1, 10)

    where = forward.position
    dropped = decide(where, worked(where, wrong=60, minutes=44, number=2), CATALOGUE)
    assert dropped.position == Position("2A", 191, 10), "back where they came from"


def test_corrections_outlive_the_night_they_were_made():
    monday = [Correction(answer_id=f"m{i}", created_on=START) for i in range(4)]
    after_monday, skipped = close_homework(monday, on=START)
    assert skipped == 4

    tuesday = after_monday + [
        Correction(answer_id="t1", created_on=START + timedelta(days=1))
    ]
    from progression import open_queue

    assert len(open_queue(tuesday)) == 5, "Monday's four are still waiting on Tuesday"

    in_centre = [
        c if c.status is CorrectionStatus.RESOLVED else
        Correction(c.answer_id, CorrectionStatus.RESOLVED, c.created_on, c.skipped_on)
        for c in tuesday
    ]
    assert open_queue(in_centre) == []
