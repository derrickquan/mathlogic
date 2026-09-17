from __future__ import annotations

from progression import AttemptResult, EventKind, Location, Packet, Position, resize


def centre(minutes, pages=10):
    return AttemptResult(
        packet=Packet("2A", 41, pages, pages * 20, Location.CENTRE),
        attempt_number=1,
        location=Location.CENTRE,
        wrong_count=0,
        active_seconds=int(minutes * 60),
    )


def home(minutes, pages=10):
    return AttemptResult(
        packet=Packet("2A", 41, pages, pages * 20, Location.HOME),
        attempt_number=1,
        location=Location.HOME,
        wrong_count=0,
        active_seconds=int(minutes * 60),
    )


TEN = Position("2A", 41, 10)
FIVE = Position("2A", 41, 5)


def test_three_slow_packets_drop_ten_to_five():
    where, events = resize(TEN, [centre(50), centre(48), centre(47)])
    assert where.packet_size == 5
    assert [e.kind for e in events] == [EventKind.PACKET_SIZE_DOWN]
    assert where.page == TEN.page, "resizing does not move the student"


def test_three_quick_packets_raise_five_to_ten():
    where, events = resize(FIVE, [centre(18, pages=5), centre(17, pages=5), centre(19, pages=5)])
    assert where.packet_size == 10
    assert [e.kind for e in events] == [EventKind.PACKET_SIZE_UP]


def test_two_slow_packets_are_not_enough():
    """Two reacts to a bad day."""
    where, events = resize(TEN, [centre(50), centre(48)])
    assert where.packet_size == 10
    assert events == ()


def test_one_good_packet_breaks_the_run():
    where, _ = resize(TEN, [centre(50), centre(30), centre(48)])
    assert where.packet_size == 10


def test_the_dead_band_stops_a_student_oscillating():
    """4.2 minutes a page is slow for ten pages and quick for five, and moves neither."""
    on_ten, events_ten = resize(TEN, [centre(42), centre(42), centre(42)])
    assert on_ten.packet_size == 10 and events_ten == ()

    on_five, events_five = resize(FIVE, [centre(21, pages=5)] * 3)
    assert on_five.packet_size == 5 and events_five == ()


def test_the_boundaries_themselves_do_not_move_anyone():
    """Exactly 45 minutes over ten pages, and exactly 20 over five."""
    on_ten, _ = resize(TEN, [centre(45)] * 3)
    assert on_ten.packet_size == 10

    on_five, _ = resize(FIVE, [centre(20, pages=5)] * 3)
    assert on_five.packet_size == 5


def test_homework_never_resizes_anything():
    """Home conditions are uncontrolled: dinner, a sibling, a child wandering off."""
    where, events = resize(TEN, [home(90), home(120), home(95)])
    assert where.packet_size == 10
    assert events == ()


def test_home_attempts_do_not_break_a_run_of_centre_ones():
    history = [centre(50), home(200), centre(48), home(5), centre(47)]
    where, _ = resize(TEN, history)
    assert where.packet_size == 5, "the three in-centre packets are what count"


def test_no_history_leaves_the_student_alone():
    where, events = resize(TEN, [])
    assert where == TEN and events == ()


def test_the_event_explains_itself():
    _, events = resize(TEN, [centre(50), centre(48), centre(47)])
    note = events[0].note
    assert "4.5" in note and "minutes a page" in note
    assert "5.0" in note, "the actual rates are in the note"
