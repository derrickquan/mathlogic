from __future__ import annotations

from datetime import date, timedelta

import pytest

from progression import (
    AttemptResult,
    EventKind,
    LevelInfo,
    Location,
    Packet,
    Position,
    StaticCatalogue,
    allowed_wrong,
    decide,
    passed,
)

# Three levels, so there is somewhere to fall back to and somewhere to go on to.
CATALOGUE = StaticCatalogue([
    LevelInfo("3A", sort_order=5, page_count=200, problems_per_page=20),
    LevelInfo("2A", sort_order=6, page_count=200, problems_per_page=20),
    LevelInfo("A", sort_order=7, page_count=200, problems_per_page=20),
])


def attempt(problem_count=200, wrong=0, number=1, location=Location.CENTRE, seconds=1800, pages=10):
    return AttemptResult(
        packet=Packet("2A", 41, pages, problem_count, location),
        attempt_number=number,
        location=location,
        wrong_count=wrong,
        active_seconds=seconds,
    )


@pytest.mark.parametrize(
    "problems, allowed",
    [(100, 5), (30, 2), (20, 1), (6, 1), (1, 1), (200, 10), (40, 2), (21, 2)],
)
def test_allowed_wrong_matches_the_spec(problems, allowed):
    assert allowed_wrong(problems) == allowed


def test_allowed_wrong_rounds_up_so_short_packets_are_not_the_harshest():
    """Five pages of six problems must not be stricter than ten pages of twenty."""
    short = allowed_wrong(30) / 30
    long = allowed_wrong(200) / 200
    assert short >= long


def test_allowed_wrong_never_drops_below_one():
    assert all(allowed_wrong(n) >= 1 for n in range(1, 500))


def test_allowed_wrong_is_never_stricter_than_five_per_cent():
    assert all(allowed_wrong(n) >= n * 0.05 for n in range(1, 500))


def test_a_packet_needs_problems():
    with pytest.raises(ValueError, match="at least one problem"):
        allowed_wrong(0)


def test_the_gate_is_at_five_per_cent():
    assert passed(attempt(200, wrong=10))
    assert not passed(attempt(200, wrong=11))


def test_passing_advances_a_whole_packet():
    where = Position("2A", 41, 10)
    outcome = decide(where, attempt(wrong=0), CATALOGUE)
    assert outcome.position == Position("2A", 51, 10)
    assert [e.kind for e in outcome.events] == [EventKind.ADVANCED]
    assert not outcome.flag_facilitator


def test_a_first_failure_repeats_the_same_packet():
    where = Position("2A", 41, 10)
    outcome = decide(where, attempt(wrong=11, number=1), CATALOGUE)
    assert outcome.position == where, "the student stays put"
    assert outcome.repeat
    assert outcome.events == (), "a repeat is not a placement event"
    assert not outcome.flag_facilitator


def test_a_second_failure_drops_a_packet_without_asking_anyone():
    where = Position("2A", 41, 10)
    outcome = decide(where, attempt(wrong=11, number=2), CATALOGUE)
    assert outcome.position == Position("2A", 31, 10)
    assert [e.kind for e in outcome.events] == [EventKind.DEMOTED_FAILURE]
    assert outcome.flag_facilitator, "someone should go and teach"
    assert not outcome.escalate_to_parents, "one drop is a bad week"


def test_dropping_off_the_front_of_a_level_lands_in_the_one_before():
    outcome = decide(Position("2A", 1, 10), attempt(wrong=99, number=2), CATALOGUE)
    assert outcome.position.level == "3A"
    assert outcome.position.page == 191, "the last whole packet of the earlier level"


def test_a_child_at_the_very_beginning_stays_put_and_gets_a_person():
    where = Position("3A", 1, 10)
    outcome = decide(where, attempt(wrong=99, number=2), CATALOGUE)
    assert outcome.position == where
    assert outcome.flag_facilitator
    assert "nowhere to drop" in outcome.events[0].note


def test_a_second_drop_within_a_month_escalates_to_the_parents():
    today = date(2026, 9, 17)
    outcome = decide(
        Position("2A", 41, 10),
        attempt(wrong=99, number=2),
        CATALOGUE,
        recent_demotions=[today - timedelta(days=12)],
        today=today,
    )
    assert outcome.escalate_to_parents, "twice in a month means the placement is wrong"


def test_an_old_drop_does_not_escalate():
    today = date(2026, 9, 17)
    outcome = decide(
        Position("2A", 41, 10),
        attempt(wrong=99, number=2),
        CATALOGUE,
        recent_demotions=[today - timedelta(days=120)],
        today=today,
    )
    assert not outcome.escalate_to_parents


def test_finishing_the_last_authored_level_asks_for_a_person():
    where = Position("A", 191, 10)
    outcome = decide(where, attempt(wrong=0), CATALOGUE)
    assert outcome.position == where
    assert outcome.flag_facilitator
    assert "nothing further to assign" in outcome.note.lower()
