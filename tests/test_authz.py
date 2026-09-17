"""Who can reach what, over HTTP, against the real database.

These are the tests that matter most in this file's subject: the ones that check
a caller cannot reach somebody else's child, and that a child handed an unlocked
tablet cannot wander into the parent view.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from api.app import create_app

pytestmark = pytest.mark.integration


@pytest.fixture
def client(service):
    with TestClient(create_app(service)) as client:
        yield client


def auth(token):
    return {"Authorization": f"Bearer {token}"}


def parent_token(client, clean, email=None):
    response = client.post("/auth/parent/login", json={
        "email": email or clean["parent_email"], "password": clean["parent_password"]})
    assert response.status_code == 200, response.text
    return response.json()["token"]


def staff_token(client, clean):
    response = client.post("/auth/staff/login", json={
        "email": clean["staff_email"], "password": clean["staff_password"]})
    assert response.status_code == 200, response.text
    return response.json()["token"]


def badge_token(client, code):
    response = client.post("/check-in", json={"badge_code": code})
    assert response.status_code == 200, response.text
    return response.json()["token"]


# ---------------------------------------------------------------------------
# Logging in
# ---------------------------------------------------------------------------


def test_a_parent_logs_in_and_sees_their_children(client, clean):
    body = client.post("/auth/parent/login", json={
        "email": clean["parent_email"], "password": clean["parent_password"]}).json()
    assert body["kind"] == "parent"
    assert [child["name"] for child in body["children"]] == ["Amara O."]
    assert "Theo B." not in str(body), "somebody else's child is not theirs to see"


def test_a_wrong_password_says_nothing_useful(client, clean):
    wrong = client.post("/auth/parent/login", json={
        "email": clean["parent_email"], "password": "not it"})
    missing = client.post("/auth/parent/login", json={
        "email": "nobody@example.test", "password": "not it"})

    assert wrong.status_code == missing.status_code == 401
    assert wrong.json() == missing.json(), (
        "the same answer either way, so the endpoint cannot be used to find out "
        "which addresses have accounts"
    )


def test_a_badge_scan_is_the_credential_at_the_centre(client, clean):
    body = client.post("/check-in", json={"badge_code": clean["badge"]}).json()
    assert body["token"]
    assert body["name"] == "Amara O."


def test_an_unknown_badge_opens_nothing(client):
    assert client.post("/check-in", json={"badge_code": "MADE-UP"}).status_code == 404


# ---------------------------------------------------------------------------
# The line between a student session and a parent one
# ---------------------------------------------------------------------------


def test_a_parent_unlocks_their_own_child_and_gets_a_student_session(client, clean):
    token = parent_token(client, clean)
    body = client.post("/auth/student/unlock",
                       json={"student_id": clean["student_id"]}, headers=auth(token)).json()

    assert body["kind"] == "student", "handing over the tablet hands over a student session"
    assert body["student_id"] == clean["student_id"]
    assert body["token"] != token


def test_a_parent_cannot_unlock_somebody_elses_child(client, clean):
    token = parent_token(client, clean)
    response = client.post("/auth/student/unlock",
                           json={"student_id": clean["other_student_id"]}, headers=auth(token))
    assert response.status_code == 403
    assert "not your child" in response.json()["detail"]


def test_a_student_session_cannot_reach_a_parents_view(client, clean):
    """The child must not be left sitting inside the parent view with their own
    scores and reports in it."""
    student = badge_token(client, clean["badge"])

    blocked = client.post("/auth/student/unlock",
                          json={"student_id": clean["student_id"]}, headers=auth(student))
    assert blocked.status_code == 403
    assert "parent session" in blocked.json()["detail"]


def test_a_student_session_cannot_reach_another_childs_work(client, clean):
    amara = badge_token(client, clean["badge"])

    response = client.get(f"/students/{clean['other_student_id']}/assignment",
                          headers=auth(amara))
    assert response.status_code == 403
    assert "not your work" in response.json()["detail"]


def test_a_parent_cannot_read_another_familys_child(client, clean):
    token = parent_token(client, clean)
    response = client.get(f"/students/{clean['other_student_id']}/corrections",
                          headers=auth(token))
    assert response.status_code == 403


def test_a_parent_can_read_their_own_childs_corrections(client, clean):
    token = parent_token(client, clean)
    response = client.get(f"/students/{clean['student_id']}/corrections", headers=auth(token))
    assert response.status_code == 200


def test_a_parent_does_not_do_the_work_themselves(client, clean):
    token = parent_token(client, clean)
    response = client.post("/attempts",
                           json={"student_id": clean["student_id"], "location": "centre"},
                           headers=auth(token))
    assert response.status_code == 403


def test_a_student_cannot_start_a_packet_for_another_student(client, clean):
    amara = badge_token(client, clean["badge"])
    response = client.post("/attempts",
                           json={"student_id": clean["other_student_id"], "location": "centre"},
                           headers=auth(amara))
    assert response.status_code == 403


def test_one_childs_session_cannot_answer_another_childs_attempt(client, clean):
    theo = badge_token(client, clean["other_badge"])
    started = client.post("/attempts",
                          json={"student_id": clean["other_student_id"], "location": "centre"},
                          headers=auth(theo)).json()

    amara = badge_token(client, clean["badge"])
    response = client.post(
        f"/attempts/{started['attempt_id']}/answers",
        json={"problem_id": "00000000-0000-0000-0000-000000000000", "ink": []},
        headers=auth(amara),
    )
    assert response.status_code == 403


# ---------------------------------------------------------------------------
# Facilitator routes
# ---------------------------------------------------------------------------


def test_the_console_needs_a_facilitator(client, clean):
    assert client.get("/console/room").status_code == 401

    student = badge_token(client, clean["badge"])
    assert client.get("/console/room", headers=auth(student)).status_code == 403

    parent = parent_token(client, clean)
    assert client.get("/console/room", headers=auth(parent)).status_code == 403

    staff = staff_token(client, clean)
    assert client.get("/console/room", headers=auth(staff)).status_code == 200


def test_clearing_a_backlog_is_a_facilitators_to_do(client, clean):
    student = badge_token(client, clean["badge"])
    response = client.post(f"/students/{clean['student_id']}/corrections/cancel",
                           headers=auth(student))
    assert response.status_code == 403, "a child cannot make their own backlog disappear"


def test_the_name_on_an_override_comes_from_the_session_not_the_body(client, clean, service,
                                                                    database):
    """A staff_id in a JSON payload is a staff_id anyone can type."""
    from progression import Location

    assignment = service.assignment(clean["student_id"], Location.CENTRE)
    started = service.start_attempt(clean["student_id"], Location.CENTRE)
    problem = assignment["pages"][0]["problems"][0]
    answered = service.submit_answer(started["attempt_id"], problem["problem_id"],
                                     [{"declared": "4", "points": []}])

    staff = staff_token(client, clean)
    a, b = (int(part) for part in problem["prompt"].split(" + "))
    response = client.post(f"/answers/{answered['answer_id']}/override",
                           json={"value": str(a + b), "staff_id": "pretend-to-be-someone"},
                           headers=auth(staff))
    assert response.status_code == 200

    with database.connection() as conn:
        row = conn.execute(
            "SELECT overridden_by FROM answers WHERE id = %s", (answered["answer_id"],)
        ).fetchone()
    assert str(row["overridden_by"]) == clean["staff_id"], "the session's owner, not the body's"


# ---------------------------------------------------------------------------
# Session lifecycle
# ---------------------------------------------------------------------------


def test_no_token_is_a_401_and_a_bad_one_is_too(client, clean):
    assert client.get(f"/students/{clean['student_id']}/corrections").status_code == 401
    assert client.get(f"/students/{clean['student_id']}/corrections",
                      headers=auth("made-up")).status_code == 401
    assert client.get(f"/students/{clean['student_id']}/corrections",
                      headers={"Authorization": "Basic hello"}).status_code == 401


def test_logging_out_ends_the_session_immediately(client, clean):
    token = parent_token(client, clean)
    assert client.get(f"/students/{clean['student_id']}/corrections",
                      headers=auth(token)).status_code == 200

    assert client.post("/auth/logout", headers=auth(token)).status_code == 200
    assert client.get(f"/students/{clean['student_id']}/corrections",
                      headers=auth(token)).status_code == 401


def test_an_expired_session_is_refused(client, clean, database):
    token = parent_token(client, clean)
    with database.connection() as conn:
        conn.execute("UPDATE sessions SET expires_at = now() - interval '1 minute'")

    assert client.get(f"/students/{clean['student_id']}/corrections",
                      headers=auth(token)).status_code == 401


def test_closing_homework_ends_the_unlock_with_it(client, clean):
    """A tablet left on the sofa should not still be open an hour later."""
    parent = parent_token(client, clean)
    student = client.post("/auth/student/unlock", json={"student_id": clean["student_id"]},
                          headers=auth(parent)).json()["token"]

    assert client.get(f"/students/{clean['student_id']}/assignment",
                      headers=auth(student)).status_code == 200

    closed = client.post(f"/students/{clean['student_id']}/close-homework", headers=auth(student))
    assert closed.status_code == 200

    assert client.get(f"/students/{clean['student_id']}/assignment",
                      headers=auth(student)).status_code == 401


def test_the_sessions_table_never_holds_a_usable_token(client, clean, database):
    token = parent_token(client, clean)
    with database.connection() as conn:
        rows = conn.execute("SELECT token_hash FROM sessions").fetchall()
    assert rows
    assert all(row["token_hash"] != token for row in rows)
    assert all(len(row["token_hash"]) == 64 for row in rows), "sha-256 hex, not the token"


def test_a_session_cannot_be_two_kinds_at_once(clean, database):
    """The schema refuses it, not just the code: a student session carrying a
    parent_id would quietly become one."""
    import psycopg

    with pytest.raises(psycopg.errors.CheckViolation):
        with database.connection() as conn:
            conn.execute(
                """
                INSERT INTO sessions (kind, token_hash, student_id, parent_id, expires_at)
                VALUES ('student', 'deadbeef', %s, %s, now() + interval '1 hour')
                """,
                (clean["student_id"], clean["parent_id"]),
            )
