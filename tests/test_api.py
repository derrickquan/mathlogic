"""The loop, against a real PostgreSQL.

These run through the service rather than HTTP where the test needs to do a
hundred things in a row, and through HTTP where the point is the route. Both hit
the same database, with the same triggers, holding the same frozen level 2A.
"""

from __future__ import annotations

import pytest

from api.service import Conflict, NotFound
from progression import Location

pytestmark = pytest.mark.integration


def calibration_samples():
    return {str(n): [{"points": [[1, 2, 3]]}] for n in range(11)}


def ink(value):
    """Stroke data plus what the writer says it is, for the stand-in recogniser."""
    return [{"declared": value, "points": [[10, 10, 2.0], [14, 30, 2.4]]}]


def answer_everything(service, attempt_id, assignment, *, wrong=0, seconds_each=3):
    """Work the whole packet. `wrong` says how many to get deliberately wrong."""
    problems = [p for page in assignment["pages"] for p in page["problems"]]
    spoiled = 0
    for problem in problems:
        a, b = (int(part) for part in problem["prompt"].split(" + "))
        value = str(a + b)
        if spoiled < wrong:
            value = str(a + b + 1)
            spoiled += 1
        service.submit_answer(attempt_id, problem["problem_id"], ink(value),
                              active_seconds=seconds_each)
    return problems


# ---------------------------------------------------------------------------
# Arriving
# ---------------------------------------------------------------------------


def test_a_badge_checks_a_student_in_and_states_their_assignment(service, clean):
    result = service.check_in(clean["badge"])
    assert result["name"] == "Amara O."
    assert result["needs_calibration"] is True, "nobody has calibrated yet"

    assignment = result["assignment"]
    assert assignment["level"] == "2A"
    assert assignment["start_page"] == 41
    assert assignment["page_count"] == 5, "this student is on five-page packets"
    assert assignment["problem_count"] == 100
    assert len(assignment["pages"]) == 5


def test_an_unknown_badge_is_refused(service):
    with pytest.raises(NotFound):
        service.check_in("NOT-A-BADGE")


def test_the_tablet_is_never_given_a_correct_answer(service, clean):
    """The invariant that makes offline capture safe and removes cheating."""
    assignment = service.check_in(clean["badge"])["assignment"]
    blob = repr(assignment)

    for page in assignment["pages"]:
        for problem in page["problems"]:
            assert set(problem) == {"problem_id", "position", "prompt", "answer_shape"}
            assert "correct_answer" not in problem

    assert "correct_answer" not in blob


def test_calibration_runs_to_ten_not_nine(service, clean):
    with pytest.raises(Conflict, match="missing"):
        service.calibrate(clean["student_id"], {str(n): [] for n in range(10)})

    result = service.calibrate(clean["student_id"], calibration_samples())
    assert result["calibrated"]
    assert result["digits"][-1] == "10"

    assert service.check_in(clean["badge"])["needs_calibration"] is False


# ---------------------------------------------------------------------------
# Working a packet
# ---------------------------------------------------------------------------


def test_a_clean_packet_advances_the_student(service, clean):
    assignment = service.assignment(clean["student_id"], Location.CENTRE)
    started = service.start_attempt(clean["student_id"], Location.CENTRE)

    answer_everything(service, started["attempt_id"], assignment)
    result = service.submit_attempt(started["attempt_id"])

    assert result["wrong_count"] == 0
    assert result["passed"]
    assert result["position"]["page"] == 46, "one packet of five pages on"
    assert [e["kind"] for e in result["events"]] == ["advanced"]


def test_five_per_cent_wrong_still_passes(service, clean):
    assignment = service.assignment(clean["student_id"], Location.CENTRE)
    started = service.start_attempt(clean["student_id"], Location.CENTRE)

    answer_everything(service, started["attempt_id"], assignment, wrong=5)
    result = service.submit_attempt(started["attempt_id"])

    assert result["wrong_count"] == 5, "100 problems allow 5"
    assert result["passed"]


def test_one_over_the_line_repeats_the_same_packet(service, clean):
    assignment = service.assignment(clean["student_id"], Location.CENTRE)
    started = service.start_attempt(clean["student_id"], Location.CENTRE)

    answer_everything(service, started["attempt_id"], assignment, wrong=6)
    result = service.submit_attempt(started["attempt_id"])

    assert not result["passed"]
    assert result["repeat"]
    assert result["position"]["page"] == 41, "same pages, same problems"
    assert result["events"] == []


def test_a_second_failure_drops_a_packet_and_flags_a_person(service, clean):
    for _ in range(2):
        assignment = service.assignment(clean["student_id"], Location.CENTRE)
        started = service.start_attempt(clean["student_id"], Location.CENTRE)
        answer_everything(service, started["attempt_id"], assignment, wrong=20)
        result = service.submit_attempt(started["attempt_id"])

    assert result["position"]["page"] == 36, "back one packet"
    assert result["flag_facilitator"]
    assert [e["kind"] for e in result["events"]] == ["demoted_failure"]


def test_a_repeat_is_a_second_attempt_on_the_same_packet(service, clean):
    assignment = service.assignment(clean["student_id"], Location.CENTRE)
    first = service.start_attempt(clean["student_id"], Location.CENTRE)
    answer_everything(service, first["attempt_id"], assignment, wrong=6)
    service.submit_attempt(first["attempt_id"])

    second = service.start_attempt(clean["student_id"], Location.CENTRE)
    assert second["packet_id"] == first["packet_id"], "the same assignment"
    assert second["attempt_number"] == 2
    assert second["attempt_id"] != first["attempt_id"]


def test_an_unfinished_packet_cannot_be_graded(service, clean):
    """A client submitting early must not advance a student on the strength of
    the problems they happened to answer."""
    assignment = service.assignment(clean["student_id"], Location.CENTRE)
    started = service.start_attempt(clean["student_id"], Location.CENTRE)

    problem = assignment["pages"][0]["problems"][0]
    service.submit_answer(started["attempt_id"], problem["problem_id"], ink("99"))

    with pytest.raises(Conflict, match="not finished: 1 of 100"):
        service.submit_attempt(started["attempt_id"])


def test_a_graded_attempt_cannot_be_graded_again(service, clean):
    assignment = service.assignment(clean["student_id"], Location.CENTRE)
    started = service.start_attempt(clean["student_id"], Location.CENTRE)
    answer_everything(service, started["attempt_id"], assignment)
    service.submit_attempt(started["attempt_id"])

    with pytest.raises(Conflict, match="append-only"):
        service.submit_attempt(started["attempt_id"])


def test_a_graded_attempt_takes_no_more_answers(service, clean):
    assignment = service.assignment(clean["student_id"], Location.CENTRE)
    started = service.start_attempt(clean["student_id"], Location.CENTRE)
    problems = answer_everything(service, started["attempt_id"], assignment)
    service.submit_attempt(started["attempt_id"])

    with pytest.raises(Conflict, match="append-only"):
        service.submit_answer(started["attempt_id"], problems[0]["problem_id"], ink("9"))


# ---------------------------------------------------------------------------
# Verdicts and corrections
# ---------------------------------------------------------------------------


def test_a_wrong_answer_joins_the_corrections_queue(service, clean):
    assignment = service.assignment(clean["student_id"], Location.CENTRE)
    started = service.start_attempt(clean["student_id"], Location.CENTRE)
    problem = assignment["pages"][0]["problems"][0]

    result = service.submit_answer(started["attempt_id"], problem["problem_id"], ink("99"))
    assert result["verdict"] == "wrong"

    queue = service.corrections(clean["student_id"])
    assert len(queue) == 1
    assert queue[0]["prompt"] == problem["prompt"]
    assert queue[0]["status"] == "pending"


def test_illegible_ink_asks_for_a_rewrite_and_does_not_join_corrections(service, clean):
    assignment = service.assignment(clean["student_id"], Location.CENTRE)
    started = service.start_attempt(clean["student_id"], Location.CENTRE)
    problem = assignment["pages"][0]["problems"][0]

    result = service.submit_answer(
        started["attempt_id"], problem["problem_id"], [{"points": [[1, 1, 1]]}]
    )
    assert result["verdict"] == "illegible"
    assert "couldn't read" in result["message"]
    assert result["rewrites_used"] == 1
    assert service.corrections(clean["student_id"]) == [], "illegible is not wrong"


def test_the_third_try_is_accepted_as_written_with_a_note_for_the_parent(service, clean, database):
    assignment = service.assignment(clean["student_id"], Location.CENTRE)
    started = service.start_attempt(clean["student_id"], Location.CENTRE)
    problem = assignment["pages"][0]["problems"][0]
    unreadable = [{"points": [[1, 1, 1]]}]

    first = service.submit_answer(started["attempt_id"], problem["problem_id"], unreadable)
    second = service.submit_answer(started["attempt_id"], problem["problem_id"], unreadable)
    third = service.submit_answer(started["attempt_id"], problem["problem_id"], unreadable)

    assert first["verdict"] == "illegible" and second["verdict"] == "illegible"
    assert third["accepted_as_written"], "two tries was enough"

    with database.connection() as conn:
        notes = conn.execute(
            "SELECT count(*) AS n FROM legibility_notes WHERE student_id = %s",
            (clean["student_id"],),
        ).fetchone()
        assert notes["n"] == 1, "a note for the parent, not a mark against the child"


def test_closing_homework_skips_what_is_left_and_keeps_it(service, clean):
    assignment = service.assignment(clean["student_id"], Location.HOME)
    started = service.start_attempt(clean["student_id"], Location.HOME)
    for problem in assignment["pages"][0]["problems"][:3]:
        service.submit_answer(started["attempt_id"], problem["problem_id"], ink("99"))

    closed = service.close_homework(clean["student_id"])
    assert closed["skipped"] == 3
    assert closed["still_outstanding"] == 3, "skipped, not gone"

    queue = service.corrections(clean["student_id"])
    assert {c["status"] for c in queue} == {"skipped"}


def test_clearing_a_backlog_drops_the_student_and_writes_the_same_kind_of_history(
    service, clean, database
):
    assignment = service.assignment(clean["student_id"], Location.HOME)
    started = service.start_attempt(clean["student_id"], Location.HOME)
    for problem in assignment["pages"][0]["problems"][:12]:
        service.submit_answer(started["attempt_id"], problem["problem_id"], ink("99"))

    result = service.cancel_backlog(clean["student_id"], clean["staff_id"])
    assert result["cancelled"] == 12
    assert result["position"]["page"] == 36
    assert service.corrections(clean["student_id"]) == []

    with database.connection() as conn:
        events = conn.execute(
            "SELECT kind, triggered_by FROM student_events WHERE student_id = %s",
            (clean["student_id"],),
        ).fetchall()
    assert [e["kind"] for e in events] == ["demoted_backlog"]
    assert str(events[0]["triggered_by"]) == clean["staff_id"], "a person did this one"


def test_cancelling_an_empty_backlog_is_refused(service, clean):
    with pytest.raises(Conflict, match="no backlog"):
        service.cancel_backlog(clean["student_id"], clean["staff_id"])


# ---------------------------------------------------------------------------
# The facilitator
# ---------------------------------------------------------------------------


def test_an_override_corrects_the_verdict_and_teaches_the_recogniser(service, clean, database):
    assignment = service.assignment(clean["student_id"], Location.CENTRE)
    started = service.start_attempt(clean["student_id"], Location.CENTRE)
    problem = assignment["pages"][0]["problems"][0]
    a, b = (int(part) for part in problem["prompt"].split(" + "))

    misread = service.submit_answer(started["attempt_id"], problem["problem_id"], ink("4"))
    assert misread["verdict"] == "wrong"

    fixed = service.override(misread["answer_id"], str(a + b), clean["staff_id"])
    assert fixed["verdict"] == "correct"

    with database.connection() as conn:
        row = conn.execute(
            "SELECT system_read, actual_value FROM recognition_corrections WHERE student_id = %s",
            (clean["student_id"],),
        ).fetchone()
    assert row["system_read"] == "4"
    assert row["actual_value"] == str(a + b)


def test_the_room_shows_who_is_in_it(service, clean):
    service.check_in(clean["badge"], tablet_id=None)
    room = service.room()
    assert len(room) == 1
    assert room[0]["full_name"] == "Amara O."


# ---------------------------------------------------------------------------
# Over HTTP
# ---------------------------------------------------------------------------


def test_the_routes_work_end_to_end(service, clean):
    from fastapi.testclient import TestClient

    from api.app import create_app

    with TestClient(create_app(service)) as client:
        assert client.get("/health").json() == {"status": "ok"}

        checked_in = client.post("/check-in", json={"badge_code": clean["badge"]})
        assert checked_in.status_code == 200
        body = checked_in.json()
        assert body["needs_calibration"] is True
        assert "correct_answer" not in checked_in.text, "not over the wire either"

        calibrated = client.post(
            f"/students/{clean['student_id']}/calibration",
            json={"samples": calibration_samples()},
        )
        assert calibrated.status_code == 200

        started = client.post(
            "/attempts", json={"student_id": clean["student_id"], "location": "centre"}
        ).json()

        problem = body["assignment"]["pages"][0]["problems"][0]
        graded = client.post(
            f"/attempts/{started['attempt_id']}/answers",
            json={"problem_id": problem["problem_id"], "ink": ink("99"), "active_seconds": 4},
        ).json()
        assert graded["verdict"] == "wrong"

        queue = client.get(f"/students/{clean['student_id']}/corrections").json()
        assert len(queue) == 1

        early = client.post(f"/attempts/{started['attempt_id']}/submit")
        assert early.status_code == 409, "an unfinished packet is not gradeable"

        assert client.post("/check-in", json={"badge_code": "nope"}).status_code == 404
