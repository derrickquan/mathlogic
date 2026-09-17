"""Walk the whole loop against a running server, narrating as it goes.

Driven by scripts/demo.sh, which stands up the database and the server first.
Everything here goes over HTTP exactly as a tablet would, with real tokens and
real authorisation — nothing reaches inside the service.
"""

from __future__ import annotations

import os
import sys

import httpx

BASE = os.environ.get("MATHLOGIC_URL", "http://127.0.0.1:8111")
PARENT_EMAIL = "parent@example.test"
PARENT_PASSWORD = "correct horse battery staple"
STAFF_EMAIL = "priya@example.test"
STAFF_PASSWORD = "a facilitators password"
BADGE = "BADGE-AMARA"
OTHER_BADGE = "BADGE-THEO"

client = httpx.Client(base_url=BASE, timeout=30.0)
failures: list[str] = []


# ---------------------------------------------------------------------------
# Narration
# ---------------------------------------------------------------------------

BOLD, DIM, GREEN, RED, AMBER, OFF = "\033[1m", "\033[2m", "\033[32m", "\033[31m", "\033[33m", "\033[0m"


def scene(title: str) -> None:
    print(f"\n{BOLD}{title}{OFF}")
    print(DIM + "─" * len(title) + OFF)


def say(text: str) -> None:
    print(f"  {text}")


def shows(label: str, value) -> None:
    print(f"  {DIM}{label:<28}{OFF}{value}")


def expect(what: str, condition: bool) -> None:
    mark = f"{GREEN}ok{OFF}" if condition else f"{RED}FAILED{OFF}"
    print(f"  {mark}  {what}")
    if not condition:
        failures.append(what)


def auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def ink(value: str) -> list[dict]:
    """Stroke data, plus what the writer says it is for the stand-in recogniser."""
    return [{"declared": value, "points": [[10, 10, 2.1], [14, 30, 2.4], [18, 44, 1.9]]}]


UNREADABLE = [{"points": [[3, 3, 1.0], [40, 41, 1.1]]}]


# ---------------------------------------------------------------------------
# The walk
# ---------------------------------------------------------------------------


def main() -> int:
    scene("1. A parent logs in")
    parent = client.post("/auth/parent/login",
                         json={"email": PARENT_EMAIL, "password": PARENT_PASSWORD})
    expect("the parent's password is accepted", parent.status_code == 200)
    parent_token = parent.json()["token"]
    shows("signed in as", parent.json()["name"])
    shows("their children", ", ".join(c["name"] for c in parent.json()["children"]))

    wrong = client.post("/auth/parent/login",
                        json={"email": PARENT_EMAIL, "password": "not the password"})
    missing = client.post("/auth/parent/login",
                          json={"email": "nobody@example.test", "password": "guessing"})
    expect("a wrong password is refused", wrong.status_code == 401)
    expect("an unknown address answers identically, so accounts cannot be enumerated",
           wrong.json() == missing.json())

    scene("2. The parent unlocks the tablet for their child")
    unlocked = client.post("/auth/student/unlock",
                           json={"student_id": parent.json()["children"][0]["student_id"]},
                           headers=auth(parent_token))
    student_token = unlocked.json()["token"]
    student_id = unlocked.json()["student_id"]
    shows("handed over to", unlocked.json()["name"])
    shows("session kind", unlocked.json()["kind"])
    expect("what comes back is a student session, not a parent one",
           unlocked.json()["kind"] == "student")

    other = client.get(f"/students/{OTHER_STUDENT[0]}/assignment", headers=auth(parent_token))
    expect("this parent cannot reach another family's child", other.status_code == 403)
    intruder = client.post("/auth/student/unlock", json={"student_id": student_id},
                           headers=auth(student_token))
    expect("the child cannot wander back into the parent view", intruder.status_code == 403)

    scene("3. Checking in at the centre with a badge")
    checked_in = client.post("/check-in", json={"badge_code": BADGE})
    body = checked_in.json()
    tablet = body["token"]
    shows("student", body["name"])
    shows("needs calibration", body["needs_calibration"])
    assignment = body["assignment"]
    shows("assigned", f"Level {assignment['level']} · pages "
                      f"{assignment['start_page']}–{assignment['end_page']}")
    shows("that is", f"{assignment['page_count']} pages, "
                     f"{assignment['problem_count']} problems")
    expect("the badge scan is the credential — nothing to type", bool(tablet))
    expect("no correct answer is anywhere in the response",
           "correct_answer" not in checked_in.text)
    say(f"{DIM}the child was not offered a choice of page; they were told one{OFF}")

    scene("4. Handwriting calibration, 0 to 10")
    samples = {str(n): ink(str(n)) for n in range(11)}
    calibrated = client.post(f"/students/{student_id}/calibration",
                             json={"samples": samples}, headers=auth(tablet))
    expect("a baseline is taken before any answer is read", calibrated.status_code == 200)
    shows("digits captured", " ".join(calibrated.json()["digits"]))

    short = client.post(f"/students/{student_id}/calibration",
                        json={"samples": {str(n): ink(str(n)) for n in range(10)}},
                        headers=auth(tablet))
    expect("stopping at 9 is refused — 10 is the level's commonest answer",
           short.status_code == 409)

    scene("5. Working the first page")
    started = client.post("/attempts",
                          json={"student_id": student_id, "location": "centre"},
                          headers=auth(tablet)).json()
    shows("attempt", f"number {started['attempt_number']}")

    page = assignment["pages"][0]
    problems = page["problems"]
    shows("page", page["page_number"])

    # Three deliberate cases: right, wrong, and unreadable.
    for index, problem in enumerate(problems):
        a, b = (int(part) for part in problem["prompt"].split(" + "))
        if index == 3:
            payload = {"problem_id": problem["problem_id"], "ink": ink(str(a + b + 1)),
                       "active_seconds": 7}
        elif index == 7:
            payload = {"problem_id": problem["problem_id"], "ink": UNREADABLE,
                       "active_seconds": 12}
        else:
            payload = {"problem_id": problem["problem_id"], "ink": ink(str(a + b)),
                       "active_seconds": 4}

        result = client.post(f"/attempts/{started['attempt_id']}/answers",
                             json=payload, headers=auth(tablet)).json()

        if index in (3, 7):
            colour = RED if result["verdict"] == "wrong" else AMBER
            print(f"  {DIM}{problem['prompt']:<8}{OFF} → {colour}{result['verdict']}{OFF}"
                  f"  “{result['message']}”")

    say("")
    say(f"{DIM}note the two messages differ: a child told only “try again” assumes{OFF}")
    say(f"{DIM}the maths was wrong and changes an answer that was right{OFF}")

    scene("6. Two rewrites, then the answer is kept as written")
    stuck = problems[7]
    for attempt_number in (2, 3):
        result = client.post(f"/attempts/{started['attempt_id']}/answers",
                             json={"problem_id": stuck["problem_id"], "ink": UNREADABLE,
                                   "active_seconds": 9},
                             headers=auth(tablet)).json()
        label = "accepted" if result["accepted_as_written"] else result["verdict"]
        print(f"  try {attempt_number}   → {AMBER}{label}{OFF}  “{result['message']}”")
    expect("no child is stuck in a loop at bedtime", result["accepted_as_written"])

    scene("7. The corrections queue")
    queue = client.get(f"/students/{student_id}/corrections", headers=auth(tablet)).json()
    for correction in queue:
        shows(f"page {correction['page_number']}",
              f"{correction['prompt']}  wrote {correction['wrote']}  ({correction['status']})")
    expect("a wrong answer went to corrections; an unreadable one did not", len(queue) == 1)

    scene("8. Submitting before the packet is finished")
    early = client.post(f"/attempts/{started['attempt_id']}/submit", headers=auth(tablet))
    shows("response", f"{early.status_code} {early.json()['detail']}")
    expect("the server will not grade a packet on the problems that happened to be done",
           early.status_code == 409)

    scene("9. Finishing the packet")
    done = 0
    for page in assignment["pages"]:
        for problem in page["problems"]:
            a, b = (int(part) for part in problem["prompt"].split(" + "))
            response = client.post(f"/attempts/{started['attempt_id']}/answers",
                                   json={"problem_id": problem["problem_id"],
                                         "ink": ink(str(a + b)), "active_seconds": 4},
                                   headers=auth(tablet))
            done += 1
    shows("answers submitted", done)

    graded = client.post(f"/attempts/{started['attempt_id']}/submit",
                         headers=auth(tablet)).json()
    shows("score", f"{graded['problem_count'] - graded['wrong_count']}"
                   f"/{graded['problem_count']}")
    shows("allowed wrong", "5  (ceil of 5% of 100)")
    shows("passed", f"{GREEN}yes{OFF}" if graded["passed"] else f"{RED}no{OFF}")
    shows("now on", f"page {graded['position']['page']}, "
                    f"{graded['position']['packet_size']}-page packets")
    for event in graded["events"]:
        shows("recorded", f"{event['kind']}")
    expect("a clean packet advances the student", graded["passed"])
    expect("the earlier wrong answer was corrected on the second pass",
           graded["wrong_count"] == 0)

    scene("10. Closing homework with work outstanding")
    client.post(f"/attempts", json={"student_id": student_id, "location": "home"},
                headers=auth(tablet))
    closed = client.post(f"/students/{student_id}/close-homework", headers=auth(tablet))
    shows("skipped", closed.json()["skipped"])
    shows("still waiting", closed.json()["still_outstanding"])

    after = client.get(f"/students/{student_id}/assignment", headers=auth(tablet))
    expect("closing homework ends the unlock — a tablet on the sofa is not still open",
           after.status_code == 401)

    scene("11. The facilitator")
    staff = client.post("/auth/staff/login",
                        json={"email": STAFF_EMAIL, "password": STAFF_PASSWORD})
    staff_token = staff.json()["token"]
    shows("signed in as", staff.json()["name"])

    room = client.get("/console/room", headers=auth(staff_token)).json()
    for seat in room:
        shows(seat["full_name"], f"{seat['active_seconds']}s working · "
                                 f"{seat['open_corrections']} corrections open")

    denied = client.get("/console/room", headers=auth(parent_token))
    expect("a parent cannot open the console", denied.status_code == 403)

    reopened = client.post("/check-in", json={"badge_code": BADGE}).json()
    child = reopened["token"]
    blocked = client.post(f"/students/{student_id}/corrections/cancel", headers=auth(child))
    expect("a child cannot make their own backlog disappear", blocked.status_code == 403)

    scene("12. Clearing a backlog drops the student back")
    home = client.post("/attempts", json={"student_id": student_id, "location": "home"},
                       headers=auth(child)).json()
    fresh = client.get(f"/students/{student_id}/assignment?location=home",
                       headers=auth(child)).json()
    for problem in fresh["pages"][0]["problems"][:11]:
        client.post(f"/attempts/{home['attempt_id']}/answers",
                    json={"problem_id": problem["problem_id"], "ink": ink("99"),
                          "active_seconds": 5},
                    headers=auth(child))

    before = client.get(f"/students/{student_id}/corrections", headers=auth(staff_token)).json()
    shows("backlog", f"{len(before)} corrections")

    cancelled = client.post(f"/students/{student_id}/corrections/cancel",
                            headers=auth(staff_token)).json()
    shows("cleared", cancelled["cancelled"])
    shows("moved to", f"page {cancelled['position']['page']}")
    say(f"  {DIM}{cancelled['note']}{OFF}")
    expect("clearing a backlog is a demotion, not a tidy-up",
           cancelled["position"]["page"] < graded["position"]["page"])

    scene("Result")
    if failures:
        print(f"  {RED}{len(failures)} expectation(s) failed:{OFF}")
        for failure in failures:
            print(f"    - {failure}")
        return 1
    print(f"  {GREEN}Every expectation held.{OFF}")
    return 0


OTHER_STUDENT: list[str] = []


if __name__ == "__main__":
    # The other family's student id, looked up once so the authorisation checks
    # above have something real to be refused.
    other = httpx.post(f"{BASE}/check-in", json={"badge_code": OTHER_BADGE}, timeout=30.0)
    OTHER_STUDENT.append(other.json()["student_id"])
    sys.exit(main())
