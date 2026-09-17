from __future__ import annotations

import pytest

from progression import (
    LevelInfo,
    Location,
    Position,
    StaticCatalogue,
    advance,
    assemble,
    from_templates,
    go_back,
)

CATALOGUE = StaticCatalogue([
    LevelInfo("3A", sort_order=5, page_count=200, problems_per_page=20),
    LevelInfo("2A", sort_order=6, page_count=200, problems_per_page=20),
    LevelInfo("A", sort_order=7, page_count=195, problems_per_page=20),
])


def test_a_packet_is_computed_from_position_and_size():
    packet = assemble(Position("2A", 41, 10), CATALOGUE, Location.CENTRE)
    assert (packet.start_page, packet.end_page, packet.page_count) == (41, 50, 10)
    assert packet.problem_count == 200
    assert packet.intended_for is Location.CENTRE


def test_packet_size_belongs_to_the_student_not_the_level():
    slow = assemble(Position("2A", 41, 5), CATALOGUE, Location.HOME)
    quick = assemble(Position("2A", 41, 10), CATALOGUE, Location.HOME)
    assert slow.page_count == 5 and quick.page_count == 10
    assert slow.start_page == quick.start_page


def test_a_packet_is_clipped_at_the_end_of_a_level_rather_than_straddling_two():
    packet = assemble(Position("A", 191, 10), CATALOGUE, Location.CENTRE)
    assert packet.page_count == 5, "level A stops at 195"
    assert packet.end_page == 195
    assert packet.problem_count == 100


def test_a_short_final_packet_is_not_a_harsher_gate():
    from progression import allowed_wrong

    short = assemble(Position("A", 191, 10), CATALOGUE, Location.CENTRE)
    full = assemble(Position("2A", 41, 10), CATALOGUE, Location.CENTRE)
    assert allowed_wrong(short.problem_count) / short.problem_count >= (
        allowed_wrong(full.problem_count) / full.problem_count
    )


def test_advancing_moves_a_whole_packet():
    assert advance(Position("2A", 41, 10), CATALOGUE) == Position("2A", 51, 10)
    assert advance(Position("2A", 41, 5), CATALOGUE) == Position("2A", 46, 5)


def test_advancing_off_the_end_of_a_level_starts_the_next_one():
    assert advance(Position("2A", 191, 10), CATALOGUE) == Position("A", 1, 10)


def test_advancing_past_the_last_authored_level_has_nowhere_to_go():
    """Not an error. A fast child reaching the end of what exists needs a person."""
    assert advance(Position("A", 191, 10), CATALOGUE) is None


def test_going_back_moves_a_whole_packet():
    assert go_back(Position("2A", 51, 10), CATALOGUE) == Position("2A", 41, 10)


def test_going_back_off_the_front_lands_on_a_whole_packet_of_the_level_before():
    where = go_back(Position("2A", 1, 10), CATALOGUE)
    assert where.level == "3A"
    assert where.page == 191
    assert (where.page - 1) % 10 == 0, "landed on a packet boundary, not partway in"


def test_going_back_respects_packet_size_at_a_level_boundary():
    where = go_back(Position("2A", 1, 5), CATALOGUE)
    assert where == Position("3A", 196, 5)


def test_there_is_nowhere_before_the_first_level():
    where = Position("3A", 1, 10)
    assert go_back(where, CATALOGUE) == where


def test_a_page_past_the_end_of_a_level_is_refused():
    with pytest.raises(ValueError, match="past the end"):
        assemble(Position("A", 300, 10), CATALOGUE, Location.CENTRE)


def test_a_position_must_be_a_real_one():
    with pytest.raises(ValueError, match="page must be at least 1"):
        Position("2A", 0, 10)
    with pytest.raises(ValueError, match="packet_size must be 5 or 10"):
        Position("2A", 1, 7)


def test_the_real_catalogue_knows_the_level_that_is_authored():
    catalogue = from_templates()
    info = catalogue.info("2A")
    assert info.page_count == 200
    assert info.problems_per_page == 20
    assert catalogue.problem_count("2A", 41, 10) == 200


def test_the_real_catalogue_has_nothing_after_2a_yet():
    catalogue = from_templates()
    assert catalogue.next_level("2A") is None
    assert catalogue.previous_level("2A") is None


def test_walking_the_whole_of_2a_covers_every_page_exactly_once():
    catalogue = from_templates()
    where = Position("2A", 1, 10)
    seen = []
    while where is not None:
        packet = assemble(where, catalogue, Location.CENTRE)
        seen.extend(range(packet.start_page, packet.end_page + 1))
        where = advance(where, catalogue)
    assert seen == list(range(1, 201)), "no page skipped, none given twice"
